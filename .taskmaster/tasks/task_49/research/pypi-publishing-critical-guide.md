# Critical Guide: Publishing pflow-cli to PyPI

## Executive Summary

Publishing pflow to PyPI requires fixing critical path issues that WILL break the application when installed via pip. This document contains everything needed to successfully publish pflow-cli.

**Package Name**: `pflow-cli` (because `pflow` is already taken on PyPI)
**Command Name**: `pflow` (stays the same)
**Critical Issues**: Resource files, config paths, and import statements must be fixed BEFORE publishing

## Part 1: Critical Code Changes Required

### 1.1 Resource File Access (MOST CRITICAL)

**THE PROBLEM**: Prompt markdown files in `src/pflow/planning/prompts/*.md` won't be accessible after pip install.

**Current Broken Code Pattern**:
```python
# This WILL FAIL after pip install:
with open("src/pflow/planning/prompts/discovery.md") as f:
    prompt = f.read()
```

**Required Fix**:
```python
# src/pflow/utils/resources.py - CREATE THIS FILE
from importlib import resources
from pathlib import Path
import json

def get_prompt(name: str) -> str:
    """Get prompt file content from package resources."""
    try:
        # Python 3.9+ preferred method
        files = resources.files('pflow.planning.prompts')
        return files.joinpath(f'{name}.md').read_text()
    except AttributeError:
        # Python 3.8 fallback
        import pkg_resources
        resource_path = pkg_resources.resource_filename(
            'pflow.planning.prompts', f'{name}.md'
        )
        with open(resource_path) as f:
            return f.read()

def get_template(name: str) -> dict:
    """Get template JSON from package resources."""
    content = resources.files('pflow.templates').joinpath(f'{name}.json').read_text()
    return json.loads(content)
```

**Update ALL prompt loading code**:
```python
# BEFORE:
prompt_path = "src/pflow/planning/prompts/workflow_generator.md"
with open(prompt_path) as f:
    prompt = f.read()

# AFTER:
from pflow.utils.resources import get_prompt
prompt = get_prompt("workflow_generator")
```

### 1.2 User Data Directory Structure

**THE PROBLEM**: Settings, workflows, and metrics need proper home directory locations.

**Required Implementation**:
```python
# src/pflow/config/paths.py - CREATE THIS FILE
from pathlib import Path
import os

def get_config_dir() -> Path:
    """Get user config directory, respecting XDG spec."""
    if xdg_config := os.environ.get('XDG_CONFIG_HOME'):
        base = Path(xdg_config)
    else:
        base = Path.home() / '.config'

    config_dir = base / 'pflow'
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_data_dir() -> Path:
    """Get user data directory, respecting XDG spec."""
    if xdg_data := os.environ.get('XDG_DATA_HOME'):
        base = Path(xdg_data)
    else:
        base = Path.home() / '.local' / 'share'

    data_dir = base / 'pflow'
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def get_cache_dir() -> Path:
    """Get cache directory for temporary data."""
    if xdg_cache := os.environ.get('XDG_CACHE_HOME'):
        base = Path(xdg_cache)
    else:
        base = Path.home() / '.cache'

    cache_dir = base / 'pflow'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

# Convenience functions for specific paths
def get_workflows_dir() -> Path:
    """Get directory for saved workflows."""
    workflows = get_data_dir() / 'workflows'
    workflows.mkdir(exist_ok=True)
    return workflows

def get_settings_file() -> Path:
    """Get path to settings.json."""
    return get_config_dir() / 'settings.json'

def get_metrics_db() -> Path:
    """Get path to metrics database."""
    return get_data_dir() / 'metrics.db'

def get_mcp_servers_dir() -> Path:
    """Get directory for MCP server installations."""
    mcp_dir = get_data_dir() / 'mcp-servers'
    mcp_dir.mkdir(exist_ok=True)
    return mcp_dir
```

**Update ALL file path references**:
```python
# BEFORE:
settings_path = "./settings.json"
workflows_dir = "./workflows"

# AFTER:
from pflow.config.paths import get_settings_file, get_workflows_dir
settings_path = get_settings_file()
workflows_dir = get_workflows_dir()
```

### 1.3 Entry Point Requirements

**File**: `src/pflow/cli/main.py`

**Required Structure**:
```python
import sys
import click

@click.group()
@click.version_option(version=__version__, prog_name="pflow")
def cli():
    """pflow - Stop paying for the same AI reasoning."""
    pass

# ... your actual CLI commands ...

# CRITICAL: This function must exist for pyproject.toml entry point
def main():
    """Entry point for console script."""
    try:
        cli()
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)  # Standard Unix exit code for SIGINT
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

## Part 2: pyproject.toml Configuration

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "pflow-cli"  # MUST be pflow-cli (pflow is taken)
version = "0.1.0"  # Start with 0.x to signal early stage
description = "Stop paying for the same AI reasoning - workflow compiler for AI agents"
readme = "README.md"
requires-python = ">=3.8"  # Don't go higher unless absolutely necessary
license = {text = "FSL-1.1-Apache-2.0"}
authors = [
    {name = "Your Name", email = "your.email@example.com"}
]
keywords = ["ai", "workflow", "automation", "cli", "llm", "orchestration"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Topic :: Software Development :: Build Tools",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "License :: Other/Proprietary License",  # FSL isn't standard
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Environment :: Console",
    "Operating System :: OS Independent",
]

dependencies = [
    "click>=8.0",
    "pydantic>=2.0",
    "rich>=13.0",  # If using rich for output
    # Add your actual dependencies
]

[project.urls]
Homepage = "https://github.com/yourusername/pflow"
Documentation = "https://github.com/yourusername/pflow#readme"
Repository = "https://github.com/yourusername/pflow"
Issues = "https://github.com/yourusername/pflow/issues"
Changelog = "https://github.com/yourusername/pflow/releases"

[project.scripts]
pflow = "pflow.cli.main:main"  # Points to main() function

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
pflow = [
    "planning/prompts/*.md",  # CRITICAL: Include prompt files
    "templates/*.json",        # Include any JSON templates
    "configs/*.yaml",          # Include any config files
    "py.typed",               # For type checking support
]
```

## Part 3: Pre-Publishing Checklist

### 3.1 Local Testing Procedure

```bash
# 1. Clean any previous builds
rm -rf dist/ build/ *.egg-info/

# 2. Build the package
python -m build

# 3. Create a fresh virtual environment
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate

# 4. Install the package locally
pip install dist/pflow_cli-0.1.0-py3-none-any.whl

# 5. CRITICAL: Change to a different directory
cd /tmp

# 6. Test all core functionality
pflow --version
pflow --help
pflow "create a test workflow"  # Test natural language
pflow workflow list              # Test workflow management
pflow registry list              # Test registry
pflow metrics                    # Test metrics

# 7. Verify file locations are correct
ls ~/.config/pflow/              # Should see settings.json
ls ~/.local/share/pflow/         # Should see workflows/, metrics.db

# 8. Deactivate and clean up
deactivate
rm -rf test_env
```

### 3.2 TestPyPI Testing

```bash
# 1. Upload to TestPyPI first
twine upload --repository testpypi dist/*

# 2. Install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ pflow-cli

# 3. Test again
cd /tmp
pflow --version
```

## Part 4: PyPI Account Setup

### 4.1 Account Creation
1. Create account at https://pypi.org/account/register/
2. Verify email address
3. Enable 2FA (recommended)

### 4.2 API Token Generation
1. Go to https://pypi.org/manage/account/token/
2. Create token with scope "Entire account" (for first upload)
3. Save token securely (starts with `pypi-`)

### 4.3 Configure Authentication
```bash
# Create ~/.pypirc
cat > ~/.pypirc << 'EOF'
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-YOUR-TOKEN-HERE

[testpypi]
username = __token__
password = pypi-YOUR-TEST-TOKEN-HERE
EOF

# Secure the file
chmod 600 ~/.pypirc
```

## Part 5: Common Failure Modes

### 5.1 Import Errors After Installation

**Symptom**: `ModuleNotFoundError: No module named 'src'`

**Cause**: Using wrong import paths

**Fix**: All imports must be from package root:
```python
# WRONG:
from src.pflow.core import something
from core import something

# CORRECT:
from pflow.core import something
```

### 5.2 File Not Found Errors

**Symptom**: `FileNotFoundError: [Errno 2] No such file or directory: 'src/pflow/planning/prompts/discovery.md'`

**Cause**: Trying to open package files with regular file operations

**Fix**: Use importlib.resources as shown in section 1.1

### 5.3 Permission Denied Errors

**Symptom**: `PermissionError: [Errno 13] Permission denied: '/usr/local/lib/python3.9/site-packages/pflow/settings.json'`

**Cause**: Trying to write to package installation directory

**Fix**: Use user directories as shown in section 1.2

### 5.4 MCP Servers Not Found

**Symptom**: MCP servers that work locally fail after pip install

**Fix**: Search multiple locations:
```python
def find_mcp_server(name: str) -> Path:
    """Find MCP server in multiple locations."""
    search_paths = [
        Path.cwd() / "node_modules" / "@modelcontextprotocol" / name,
        Path.home() / ".pflow" / "mcp-servers" / name,
        Path("/usr/local/lib/pflow/mcp-servers") / name,
    ]

    for path in search_paths:
        if path.exists():
            return path

    raise FileNotFoundError(f"MCP server '{name}' not found")
```

## Part 6: Publishing Commands

### 6.1 Build Commands
```bash
# Install build tools
pip install --upgrade build twine

# Build the package
python -m build

# Check the build
twine check dist/*
```

### 6.2 Upload Commands
```bash
# Upload to TestPyPI (recommended first)
twine upload --repository testpypi dist/*

# Upload to real PyPI (after testing)
twine upload dist/*
```

### 6.3 Verification
```bash
# Wait 1-2 minutes for CDN propagation, then:
pip install pflow-cli
pflow --version
```

## Part 7: Post-Publishing

### 7.1 README.md Update
```markdown
## Installation

```bash
pip install pflow-cli
```

## Quick Start

```bash
# Create a workflow from natural language
pflow "analyze my git commits from last week"

# Run the saved workflow
pflow run git-analyzer --time_period="7 days"

# See savings
pflow metrics
```
```

### 7.2 GitHub Release
```bash
git tag v0.1.0
git push origin v0.1.0
# Create release on GitHub with changelog
```

### 7.3 Announcement Template
```
Show HN: pflow - Stop paying for the same AI reasoning

Every time you ask Claude to analyze your commits, you pay $0.73 for the same thinking.

pflow compiles natural language to workflows once, then runs them forever for free.

Install: pip install pflow-cli
Docs: github.com/username/pflow

Example:
$ pflow "analyze git commits and create report"
→ Saved as 'commit-analyzer' (one-time compilation)
$ pflow run commit-analyzer  # Instant, free, forever
```

## Critical Success Factors

1. **Test locally with pip install before uploading**
2. **Use TestPyPI first** - it's more forgiving
3. **Fix all path issues** - they're the #1 cause of failures
4. **Include package data** - prompt files must be in the wheel
5. **Use pflow-cli as package name** - pflow is taken

## Emergency Fixes

If something breaks after publishing:
1. You CANNOT delete a version from PyPI
2. You CAN upload a new version (0.1.1) with fixes
3. You CAN yank a broken version (marks as "don't use")

```bash
# If 0.1.0 is broken:
# 1. Fix the issue
# 2. Bump version to 0.1.1
# 3. Build and upload new version
python -m build
twine upload dist/*pflow_cli-0.1.1*

# 4. Optionally yank broken version
pip install -U twine
twine yank pflow-cli==0.1.0
```

## Remember

The most common failure is resource files not being accessible after pip install. If you fix nothing else, fix the prompt file loading using importlib.resources. Everything else can be patched in 0.1.1.