# Implementation Plan: Complete Node Filtering System with settings.json

## Overview

Implement a comprehensive node filtering system that:
1. Hides test nodes from users by default (fixes CI)
2. Provides fine-grained control via `~/.pflow/settings.json`
3. Supports MCP node filtering
4. Maintains backward compatibility

## Solution Architecture

### Priority Order (highest to lowest)
1. Environment variables (for CI/testing)
2. User settings.json file
3. Default behavior (production nodes only)

### Components

```
┌─────────────────────────────────────────────┐
│           Environment Variables              │
│         PFLOW_INCLUDE_TEST_NODES            │ (Highest Priority)
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│         ~/.pflow/settings.json              │
│     allow/deny patterns for nodes           │ (User Config)
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│          Default Behavior                   │
│      (exclude test.*, include all else)     │ (Fallback)
└─────────────────────────────────────────────┘
```

## Implementation Steps

### Step 1: Create Settings System (New File)

**File: `src/pflow/core/settings.py`**

```python
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from fnmatch import fnmatch
from pydantic import BaseModel, Field

class NodeFilterSettings(BaseModel):
    """Node filtering configuration."""
    allow: List[str] = Field(default_factory=lambda: ["*"])  # Default: allow all
    deny: List[str] = Field(default_factory=lambda: ["test.*"])  # Default: deny test nodes

class RegistrySettings(BaseModel):
    """Registry-specific settings."""
    nodes: NodeFilterSettings = Field(default_factory=NodeFilterSettings)
    include_test_nodes: bool = Field(default=False)  # Can be overridden by env var

class PflowSettings(BaseModel):
    """Main settings configuration."""
    version: str = Field(default="1.0.0")
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    env: Dict[str, str] = Field(default_factory=dict)

class SettingsManager:
    """Manages pflow settings with environment variable override support."""

    def __init__(self, settings_path: Optional[Path] = None):
        self.settings_path = settings_path or Path.home() / ".pflow" / "settings.json"
        self._settings: Optional[PflowSettings] = None

    def load(self) -> PflowSettings:
        """Load settings with environment variable overrides."""
        if self._settings is None:
            self._settings = self._load_from_file()
            self._apply_env_overrides(self._settings)
        return self._settings

    def _load_from_file(self) -> PflowSettings:
        """Load settings from file or return defaults."""
        if self.settings_path.exists():
            try:
                with open(self.settings_path, 'r') as f:
                    data = json.load(f)
                return PflowSettings(**data)
            except Exception:
                # If file is corrupted, use defaults
                return PflowSettings()
        return PflowSettings()

    def _apply_env_overrides(self, settings: PflowSettings) -> None:
        """Apply environment variable overrides."""
        # Check for test node inclusion override
        if os.getenv("PFLOW_INCLUDE_TEST_NODES"):
            include_test = os.getenv("PFLOW_INCLUDE_TEST_NODES", "false").lower() in ("true", "1", "yes")
            settings.registry.include_test_nodes = include_test

            # If including test nodes, remove test.* from deny list
            if include_test and "test.*" in settings.registry.nodes.deny:
                settings.registry.nodes.deny.remove("test.*")

    def should_include_node(self, node_name: str) -> bool:
        """Check if a node should be included based on settings."""
        settings = self.load()

        # Special handling for test nodes via env var
        if settings.registry.include_test_nodes:
            # Remove test exclusions temporarily
            deny_patterns = [p for p in settings.registry.nodes.deny if not p.startswith("test")]
        else:
            deny_patterns = settings.registry.nodes.deny

        # Check deny patterns first
        for pattern in deny_patterns:
            if fnmatch(node_name, pattern):
                return False

        # Check allow patterns
        for pattern in settings.registry.nodes.allow:
            if fnmatch(node_name, pattern):
                return True

        # Default to exclude if no patterns match
        return False

    def save(self, settings: PflowSettings) -> None:
        """Save settings to file."""
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.settings_path, 'w') as f:
            json.dump(settings.model_dump(), f, indent=2)
```

### Step 2: Update Registry to Use Settings

**File: `src/pflow/registry/registry.py`** (modifications)

```python
# Add imports at top
from pflow.core.settings import SettingsManager

class Registry:
    def __init__(self, registry_path: Optional[Path] = None):
        # ... existing code ...
        self.settings_manager = SettingsManager()  # Add settings manager

    def _auto_discover_core_nodes(self) -> None:
        """Auto-discover and save core nodes on first use."""
        import pflow.nodes
        from pflow.registry.scanner import scan_for_nodes

        # Load settings for filtering
        settings = self.settings_manager.load()

        # Find core nodes directory
        nodes_path = Path(pflow.nodes.__file__).parent

        # Get all subdirectories (remove hardcoded test filtering)
        subdirs = [
            d
            for d in nodes_path.iterdir()
            if d.is_dir() and not d.name.startswith("__")
        ]

        # Discover all nodes first
        all_discovered_nodes = {}
        for subdir in subdirs:
            try:
                module_path = f"pflow.nodes.{subdir.name}"
                nodes = scan_for_nodes(module_path)
                all_discovered_nodes.update(nodes)
            except Exception:
                continue

        # Apply filtering based on settings
        filtered_nodes = {}
        for node_name, node_data in all_discovered_nodes.items():
            if self.settings_manager.should_include_node(node_name):
                filtered_nodes[node_name] = node_data

        # Register filtered nodes
        for node_name, node_data in filtered_nodes.items():
            self.register_node(
                node_name=node_name,
                module_path=node_data["module_path"],
                class_name=node_data["class_name"],
                metadata=node_data.get("metadata"),
                interface=node_data.get("interface"),
            )

        # Save to file
        self.save()

    def list_nodes(self, include_test: bool = False) -> list[str]:
        """List all available nodes with optional test node inclusion."""
        # Check environment override
        if os.getenv("PFLOW_INCLUDE_TEST_NODES", "false").lower() in ("true", "1", "yes"):
            include_test = True

        nodes = []
        for node_name in self._nodes.keys():
            if include_test or self.settings_manager.should_include_node(node_name):
                nodes.append(node_name)

        # Include MCP nodes (these are always filtered by settings)
        for node_name in self._cached_nodes.keys():
            if node_name.startswith("mcp-") and self.settings_manager.should_include_node(node_name):
                nodes.append(node_name)

        return sorted(nodes)
```

### Step 3: Update Test Configuration

**File: `tests/conftest.py`** (add to existing file)

```python
import os
import pytest

@pytest.fixture(autouse=True, scope="session")
def enable_test_nodes():
    """Enable test nodes for all test runs."""
    # Store original value
    original = os.environ.get("PFLOW_INCLUDE_TEST_NODES")

    # Set test environment
    os.environ["PFLOW_INCLUDE_TEST_NODES"] = "true"

    yield

    # Restore original value
    if original is None:
        os.environ.pop("PFLOW_INCLUDE_TEST_NODES", None)
    else:
        os.environ["PFLOW_INCLUDE_TEST_NODES"] = original
```

### Step 4: Add CLI Commands for Settings Management

**File: `src/pflow/cli/commands/settings.py`** (new file)

```python
import click
import json
from pathlib import Path
from pflow.core.settings import SettingsManager, PflowSettings

@click.group()
def settings():
    """Manage pflow settings."""
    pass

@settings.command()
def init():
    """Initialize settings with defaults."""
    manager = SettingsManager()
    default_settings = PflowSettings()
    manager.save(default_settings)
    click.echo(f"Created settings file at: {manager.settings_path}")
    click.echo("Default settings:")
    click.echo(json.dumps(default_settings.model_dump(), indent=2))

@settings.command()
def show():
    """Show current settings."""
    manager = SettingsManager()
    settings = manager.load()
    click.echo(json.dumps(settings.model_dump(), indent=2))

@settings.command()
@click.argument("pattern")
def allow(pattern: str):
    """Add an allow pattern for nodes."""
    manager = SettingsManager()
    settings = manager.load()
    if pattern not in settings.registry.nodes.allow:
        settings.registry.nodes.allow.append(pattern)
        manager.save(settings)
        click.echo(f"Added allow pattern: {pattern}")
    else:
        click.echo(f"Pattern already exists: {pattern}")

@settings.command()
@click.argument("pattern")
def deny(pattern: str):
    """Add a deny pattern for nodes."""
    manager = SettingsManager()
    settings = manager.load()
    if pattern not in settings.registry.nodes.deny:
        settings.registry.nodes.deny.append(pattern)
        manager.save(settings)
        click.echo(f"Added deny pattern: {pattern}")
    else:
        click.echo(f"Pattern already exists: {pattern}")
```

### Step 5: Update MCP Registrar for Filtering

**File: `src/pflow/mcp/registrar.py`** (modifications)

```python
# Add import
from pflow.core.settings import SettingsManager

class MCPRegistrar:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.settings_manager = SettingsManager()

    def register_tool(self, server_name: str, tool: dict) -> None:
        """Register an MCP tool with the registry."""
        # Generate node name
        node_name = f"mcp-{server_name}-{tool['name']}"

        # Check if node should be included based on settings
        if not self.settings_manager.should_include_node(node_name):
            # Skip registration if filtered out
            return

        # ... rest of existing registration code ...
```

## Testing Strategy

### Test Scenarios

1. **Default User Experience**
   - No settings.json, no env vars → test nodes hidden
   - Verify `pflow registry list` excludes test nodes

2. **Test Environment**
   - PFLOW_INCLUDE_TEST_NODES=true → test nodes visible
   - All existing tests pass

3. **Settings.json Control**
   - Create custom allow/deny patterns
   - Verify filtering works correctly

4. **MCP Node Filtering**
   - Test MCP nodes respect allow/deny patterns
   - Verify mcp-* patterns work

5. **Priority Order**
   - Env var overrides settings.json
   - Settings.json overrides defaults

### Validation Commands

```bash
# Test 1: Default behavior (no test nodes)
rm ~/.pflow/settings.json 2>/dev/null
unset PFLOW_INCLUDE_TEST_NODES
pflow registry list  # Should not show echo or test nodes

# Test 2: Environment variable override
PFLOW_INCLUDE_TEST_NODES=true pflow registry list  # Should show test nodes

# Test 3: Settings.json deny pattern
pflow settings init
pflow settings deny "github.delete-*"
pflow registry list  # Should not show github.delete-* nodes

# Test 4: Run tests (should pass)
make test

# Test 5: MCP filtering
pflow settings deny "mcp-github-*"
pflow registry list  # Should not show mcp-github-* tools
```

## Migration Path

1. **Immediate**: Implement without breaking changes
2. **First Run**: Auto-create default settings.json if missing
3. **Documentation**: Add settings guide to README
4. **Future**: Add more granular controls as needed

## Risk Mitigation

1. **Test Breakage**: Environment variable ensures tests work
2. **User Confusion**: Clear error messages when nodes are filtered
3. **MCP Compatibility**: Separate filtering logic for MCP nodes
4. **Performance**: Cache filtered results to avoid repeated filtering

## Success Metrics

- ✅ CI tests pass without echo node in user registry
- ✅ `pflow registry list` respects settings.json
- ✅ Environment variable overrides work
- ✅ MCP nodes can be filtered
- ✅ All existing tests pass
- ✅ Clear documentation for users

## Implementation Order

1. Create SettingsManager class and tests
2. Update Registry to use SettingsManager
3. Add test environment configuration
4. Update MCP registrar
5. Add CLI commands for settings
6. Comprehensive testing
7. Documentation updates

Total estimated time: 3-4 hours