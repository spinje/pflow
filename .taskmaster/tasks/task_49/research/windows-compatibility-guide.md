# Windows Compatibility Guide for pflow-cli

## Executive Summary

Adding Windows support to pflow requires minimal changes (15-20 minutes) and doubles the potential user base. The primary requirement is using `platformdirs` for cross-platform paths. Most features will work on Windows except for Unix-specific shell commands.

**Time Investment**: 15-20 minutes
**User Base Impact**: +47% potential users (Windows developers)
**Complexity**: Low (mostly path handling)

## Part 1: Required Changes for Windows Support

### 1.1 Add platformdirs Dependency

**File**: `pyproject.toml`
```toml
dependencies = [
    "click>=8.0",
    "pydantic>=2.0",
    "platformdirs>=3.0",  # ADD THIS for cross-platform support
    # ... other dependencies
]
```

### 1.2 Update Path Configuration

**File**: `src/pflow/config/paths.py`

Replace the entire paths module with:

```python
"""Cross-platform path configuration for pflow."""
from pathlib import Path
from platformdirs import user_config_dir, user_data_dir, user_cache_dir

def get_config_dir() -> Path:
    """
    Get user config directory, cross-platform.

    Returns:
    - Windows: C:\\Users\\Username\\AppData\\Roaming\\pflow
    - macOS: ~/Library/Application Support/pflow
    - Linux: ~/.config/pflow
    """
    config_dir = Path(user_config_dir("pflow", appauthor=False))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir

def get_data_dir() -> Path:
    """
    Get user data directory, cross-platform.

    Returns:
    - Windows: C:\\Users\\Username\\AppData\\Local\\pflow
    - macOS: ~/Library/Application Support/pflow
    - Linux: ~/.local/share/pflow
    """
    data_dir = Path(user_data_dir("pflow", appauthor=False))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def get_cache_dir() -> Path:
    """
    Get cache directory, cross-platform.

    Returns:
    - Windows: C:\\Users\\Username\\AppData\\Local\\pflow\\Cache
    - macOS: ~/Library/Caches/pflow
    - Linux: ~/.cache/pflow
    """
    cache_dir = Path(user_cache_dir("pflow", appauthor=False))
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

# Convenience functions remain the same
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

### 1.3 Fix File Permission Code

**Pattern to fix throughout codebase**:

```python
# BROKEN on Windows:
os.chmod(file_path, 0o600)

# FIXED:
import platform

def secure_file(file_path: Path):
    """Make file readable only by owner (Unix only)."""
    if platform.system() != "Windows":
        os.chmod(file_path, 0o600)
```

### 1.4 Update ShellNode for Basic Windows Support

**File**: `src/pflow/nodes/shell/shell_node.py` (or wherever ShellNode is)

```python
import platform
import subprocess
from pathlib import Path

class ShellNode(BaseNode):
    """Execute shell commands with cross-platform support."""

    def exec(self, prep_result):
        command = prep_result['command']

        # Platform-specific shell execution
        system = platform.system()

        if system == "Windows":
            # Windows: Use cmd.exe by default
            # Note: PowerShell could be an option with shell=True, executable='powershell.exe'
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=prep_result.get('timeout', 30),
                cwd=prep_result.get('cwd'),
                env={**os.environ, **prep_result.get('env', {})},
                # Windows-specific: explicit shell
                executable=os.environ.get('COMSPEC', 'cmd.exe')
            )
        else:
            # macOS/Linux: Use default shell
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=prep_result.get('timeout', 30),
                cwd=prep_result.get('cwd'),
                env={**os.environ, **prep_result.get('env', {})}
            )

        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'exit_code': result.returncode
        }
```

## Part 2: MCP Server Compatibility

### 2.1 NPX Command Differences

**Pattern to fix**:

```python
import platform

def run_mcp_server_command(server_name: str, args: list):
    """Run MCP server with correct command for platform."""
    system = platform.system()

    if system == "Windows":
        # Windows uses .cmd extension for npm/npx
        base_cmd = ["npx.cmd"]
    else:
        # Unix systems
        base_cmd = ["npx"]

    full_cmd = base_cmd + [f"@modelcontextprotocol/{server_name}"] + args

    return subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        check=False
    )
```

### 2.2 MCP Server Discovery

```python
def find_mcp_server(name: str) -> Path:
    """Find MCP server, checking platform-specific locations."""
    system = platform.system()

    # Common search paths
    search_paths = [
        Path.cwd() / "node_modules" / "@modelcontextprotocol" / name,
        get_mcp_servers_dir() / name,
    ]

    # Add Windows-specific paths
    if system == "Windows":
        # Windows: Check Program Files for global npm
        if program_files := os.environ.get('ProgramFiles'):
            search_paths.append(
                Path(program_files) / "nodejs" / "node_modules" / "@modelcontextprotocol" / name
            )
    else:
        # Unix: Check system locations
        search_paths.extend([
            Path("/usr/local/lib/node_modules/@modelcontextprotocol") / name,
            Path.home() / ".npm-global/lib/node_modules/@modelcontextprotocol" / name,
        ])

    for path in search_paths:
        if path.exists():
            return path

    raise FileNotFoundError(f"MCP server '{name}' not found")
```

## Part 3: Platform-Specific Limitations

### 3.1 ShellNode Command Compatibility

**Document these limitations clearly**:

| Unix Command | Windows Equivalent | Works in ShellNode? |
|-------------|-------------------|-------------------|
| `ls` | `dir` | ❌ No (unless in WSL/Git Bash) |
| `grep` | `findstr` | ❌ No (different syntax) |
| `cat` | `type` | ❌ No |
| `pwd` | `cd` (no args) | ❌ No |
| `rm` | `del` | ❌ No |
| `cp` | `copy` | ❌ No |
| `mv` | `move` | ❌ No |
| `curl` | `curl` (if installed) | ⚠️ Maybe |
| `git` | `git` | ✅ Yes (if installed) |
| `python` | `python` or `py` | ✅ Yes |
| `npm/npx` | `npm/npx` | ✅ Yes (if installed) |

### 3.2 Features That Work on Windows

✅ **Fully Functional**:
- Natural language → workflow compilation
- Workflow execution (non-shell nodes)
- MCP server integration (with npx.cmd)
- LLM nodes
- File I/O nodes (using Python APIs)
- GitHub/Git nodes (if git installed)
- Metrics and tracking
- Registry CLI
- Named workflows

⚠️ **Partially Functional**:
- ShellNode (Windows commands only)
- Commands with pipes (cmd.exe syntax different)

❌ **Non-Functional** (without WSL):
- Unix-specific commands in ShellNode
- Shell scripts (.sh files)
- Unix pipes and redirects syntax

## Part 4: Testing on Windows

### 4.1 Local Testing Without Windows Machine

**Option 1: GitHub Actions**
```yaml
# .github/workflows/windows-test.yml
name: Windows Compatibility Test

on: [push, pull_request]

jobs:
  test-windows:
    runs-on: windows-latest
    steps:
    - uses: actions/checkout@v2
    - uses: actions/setup-python@v2
      with:
        python-version: '3.9'
    - name: Install pflow
      run: |
        pip install -e .
    - name: Test basic functionality
      run: |
        pflow --version
        pflow --help
        pflow "create test workflow"
    - name: Check paths
      run: |
        python -c "from pflow.config.paths import get_config_dir; print(get_config_dir())"
```

**Option 2: Ask a Windows Friend**
```bash
# Quick test script for Windows friend
pip install pflow-cli
pflow --version
pflow "analyze some text"
pflow workflow list
echo "Did it work? Any errors?"
```

### 4.2 Windows-Specific Test Cases

```python
# test_windows_compatibility.py
import platform
import pytest
from pathlib import Path
from pflow.config.paths import get_config_dir, get_data_dir

@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only test")
def test_windows_paths():
    """Test that Windows paths are created correctly."""
    config = get_config_dir()
    data = get_data_dir()

    # Should be in AppData
    assert "AppData" in str(config)
    assert "AppData" in str(data)

    # Should exist
    assert config.exists()
    assert data.exists()

@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only test")
def test_windows_shell_node():
    """Test basic Windows commands in ShellNode."""
    from pflow.nodes.shell import ShellNode

    node = ShellNode()
    result = node.exec({"command": "echo Hello Windows"})

    assert result['exit_code'] == 0
    assert "Hello Windows" in result['stdout']
```

## Part 5: Documentation Updates

### 5.1 README.md Platform Section

```markdown
## Platform Support

pflow-cli works on Windows, macOS, and Linux with some platform-specific considerations:

| Platform | Support Level | Notes |
|----------|--------------|-------|
| macOS | ✅ Full | All features supported |
| Linux | ✅ Full | All features supported |
| Windows | ⚠️ Partial | See limitations below |

### Windows Limitations

- **ShellNode**: Only Windows commands work (`dir`, `type`, etc.). Unix commands (`ls`, `grep`) require WSL or Git Bash
- **Pipes**: Windows cmd.exe pipe syntax differs from Unix
- **File paths**: Use forward slashes or raw strings for paths

### Windows Quick Start

```powershell
# Install
pip install pflow-cli

# Create workflow (works fully)
pflow "analyze this text and summarize it"

# Use Windows commands in ShellNode
pflow "run dir command and count files"  # Works
pflow "run ls command"  # Won't work without WSL
```
```

### 5.2 Troubleshooting Section

```markdown
## Windows Troubleshooting

### Issue: "npx not found"
**Solution**: Install Node.js from nodejs.org, or use:
```powershell
winget install OpenJS.NodeJS
```

### Issue: Unix commands don't work
**Solution**: Install Git Bash or WSL, or use Windows equivalents:
- Instead of `ls`, use `dir`
- Instead of `cat file.txt`, use `type file.txt`
- Instead of `grep pattern`, use `findstr pattern`

### Issue: File paths with backslashes cause errors
**Solution**: Use forward slashes or raw strings:
```python
# Good
"C:/Users/Name/file.txt"
r"C:\Users\Name\file.txt"

# Bad
"C:\Users\Name\file.txt"  # Backslash escapes cause issues
```
```

## Part 6: Implementation Checklist

### Minimal Windows Support (15 minutes)
- [ ] Add `platformdirs>=3.0` to dependencies
- [ ] Update `paths.py` to use platformdirs
- [ ] Add platform check for chmod operations
- [ ] Update README with platform support section
- [ ] Test basic workflow creation/execution

### Enhanced Windows Support (1 hour)
- [ ] Update ShellNode with Windows command detection
- [ ] Add Windows command aliases (ls→dir mapping)
- [ ] Improve MCP server discovery for Windows
- [ ] Add Windows-specific tests
- [ ] Create Windows installation guide

### Full Windows Support (future)
- [ ] PowerShell node for Windows
- [ ] Automatic command translation
- [ ] Windows installer (.msi)
- [ ] Windows-specific example workflows

## Part 7: Quick Decision Tree

```
Should you add Windows support for v0.1.0?
├─ Do you want 2x more potential users? → YES
│  └─ Add platformdirs (15 min) → Ship
└─ Do you want simpler launch? → NO
   └─ Document "Unix only" → Ship

Recommendation: Add platformdirs. It's 15 minutes for 2x users.
```

## Conclusion

Windows support via `platformdirs` is a high-ROI investment:
- **Cost**: 15-20 minutes
- **Benefit**: 47% more potential users
- **Risk**: Minimal (worst case: some features don't work)
- **Maintenance**: Low (platformdirs handles complexity)

Even with ShellNode limitations, Windows users can:
1. Use natural language to create workflows
2. Execute Python/API-based workflows
3. Save and reuse workflows
4. Track metrics and savings
5. Use MCP servers

This is enough value to justify the minimal implementation effort.