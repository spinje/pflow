# MCP Smart Sync Implementation Plan

## Overview
Implement efficient MCP auto-discovery that only syncs when `~/.pflow/mcp-servers.json` has been modified, eliminating unnecessary overhead on every pflow run.

## Core Principle
- **No changes = No sync = No overhead** (99% of runs)
- **Config changed = Full sync = Clean slate** (handles all edge cases including renames)

## Implementation Steps

### Step 1: Add Registry Metadata Support
**File**: `src/pflow/registry/registry.py`

The Registry needs to store metadata like last sync timestamp:

```python
class Registry:
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value from registry."""
        config = self.load()
        metadata = config.get("__metadata__", {})
        return metadata.get(key, default)

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata value in registry."""
        config = self.load(include_filtered=True)
        if "__metadata__" not in config:
            config["__metadata__"] = {}
        config["__metadata__"][key] = value
        self.save(config)
```

**Note**: Check if Registry already has metadata support - if not, add it.

### Step 2: Modify Auto-Discovery Logic
**File**: `src/pflow/cli/main.py` - `_auto_discover_mcp_servers()` function

Replace current implementation with smart sync:

```python
def _auto_discover_mcp_servers(ctx: click.Context, verbose: bool) -> None:
    """Smart auto-discovery that only syncs when config changes."""
    try:
        from pflow.mcp import MCPDiscovery, MCPRegistrar, MCPServerManager
        from pflow.registry import Registry

        # Check if we should show progress
        output_controller = _get_output_controller(ctx)
        show_progress = output_controller.is_interactive()

        # Load MCP server configuration
        manager = MCPServerManager()
        config_path = manager.config_path

        # Check if config exists
        if not config_path.exists():
            # No config, nothing to sync
            return

        servers = manager.list_servers()
        if not servers:
            # No servers configured, nothing to do
            return

        # Check if sync is needed
        registry = Registry()
        config_mtime = config_path.stat().st_mtime
        last_sync = registry.get_metadata("mcp_last_sync_time", 0)
        last_sync_hash = registry.get_metadata("mcp_servers_hash", "")

        # Calculate current servers hash (for extra safety)
        current_servers = sorted(servers)
        current_hash = hashlib.md5(
            json.dumps(current_servers).encode()
        ).hexdigest()

        # Skip sync if config hasn't changed AND server list is same
        if config_mtime <= last_sync and current_hash == last_sync_hash:
            logger.debug(
                f"MCP config unchanged since last sync "
                f"(mtime={config_mtime}, last_sync={last_sync}), "
                f"skipping discovery"
            )
            return

        # Config changed or first run - do full sync
        if show_progress and not verbose:
            click.echo("🔄 MCP config changed, syncing servers...", err=True)

        # CRITICAL: Remove ALL existing MCP entries first
        # This handles renames cleanly
        all_nodes = registry.list_nodes()
        existing_mcp_count = len([n for n in all_nodes if n.startswith("mcp-")])

        if existing_mcp_count > 0:
            # Load full registry including filtered nodes
            nodes = registry.load(include_filtered=True)
            removed = 0
            for node_name in list(nodes.keys()):
                if node_name.startswith("mcp-"):
                    del nodes[node_name]
                    removed += 1

            if removed > 0:
                registry.save(nodes)
                logger.debug(f"Removed {removed} old MCP entries for clean sync")

        # Now discover and register from all servers
        discovery = MCPDiscovery(manager)
        registrar = MCPRegistrar(registry=registry, manager=manager)

        total_tools = 0
        failed_servers = []

        for server_name in servers:
            try:
                if show_progress and verbose:
                    click.echo(f"Discovering tools from MCP server '{server_name}'...", err=True)

                # Discover tools (pass verbose to control stderr)
                tools = discovery.discover_tools(server_name, verbose=effective_verbose)

                if tools:
                    # Register the discovered tools
                    registrar.register_tools(server_name, tools)
                    total_tools += len(tools)

                    if show_progress and verbose:
                        click.echo(f"  ✓ Discovered {len(tools)} tool(s) from {server_name}", err=True)
            except Exception as e:
                logger.debug(f"Failed to discover tools from {server_name}: {e}")
                failed_servers.append(server_name)
                if show_progress and verbose:
                    click.echo(f"  ⚠ Failed to connect to {server_name}", err=True)

        # Update metadata for next run
        registry.set_metadata("mcp_last_sync_time", time.time())
        registry.set_metadata("mcp_servers_hash", current_hash)

        # Show summary
        if show_progress and total_tools > 0 and not verbose:
            click.echo(
                f"✓ Synced {total_tools} MCP tool(s) from "
                f"{len(servers) - len(failed_servers)} server(s)",
                err=True
            )

        if show_progress and failed_servers and verbose:
            click.echo(
                f"⚠ Failed to connect to {len(failed_servers)} server(s): "
                f"{', '.join(failed_servers)}",
                err=True
            )

    except ImportError as e:
        logger.debug(f"MCP modules not available: {e}")
    except Exception as e:
        logger.debug(f"Failed to auto-discover MCP servers: {e}")
```

### Step 3: Add Required Imports
Add these imports to `src/pflow/cli/main.py`:
```python
import hashlib
import json
import time
```

### Step 4: Update Manual Sync Command
**File**: `src/pflow/cli/mcp.py`

The `pflow mcp sync` command should also update the timestamp:

```python
@mcp.command()
def sync(...):
    # ... existing sync logic ...

    # Update sync metadata after successful sync
    from pflow.registry import Registry
    import time

    registry = Registry()
    registry.set_metadata("mcp_last_sync_time", time.time())

    # Store hash of current servers
    manager = MCPServerManager()
    servers = sorted(manager.list_servers())
    servers_hash = hashlib.md5(json.dumps(servers).encode()).hexdigest()
    registry.set_metadata("mcp_servers_hash", servers_hash)
```

## Edge Cases & Considerations

### 1. Registry Corruption/Deletion
- If registry is deleted, metadata is lost → `last_sync = 0` → triggers sync ✅
- Self-healing behavior

### 2. Config File Corruption
- If config file is corrupted, `manager.list_servers()` will fail
- Error is caught and logged, no crash

### 3. Clock Issues
- If system time goes backwards, might not detect changes
- Mitigation: Also check servers hash as backup

### 4. Concurrent Access
- Multiple pflow instances might sync simultaneously
- Registry has atomic write protection, so safe

### 5. Permission Issues
- If can't write to registry, sync fails gracefully
- Next run will retry

### 6. First Run Experience
- No metadata exists → triggers sync
- Expected and correct behavior

### 7. Manual Config Edits
- Any edit updates mtime → triggers sync
- Even if content is identical (conservative but safe)

## Testing Strategy

### Test 1: No Changes
```bash
# Run twice, second should be instant
time uv run pflow "test"
time uv run pflow "test"  # Should skip discovery
```

### Test 2: Config Change
```bash
uv run pflow "test"  # Initial run
pflow mcp add ./new-server.json  # Modifies config
uv run pflow "test"  # Should trigger sync
```

### Test 3: Server Rename
```bash
# Manually edit ~/.pflow/mcp-servers.json
# Rename "slack-composio" to "slack-renamed"
uv run pflow "test"  # Should remove old, add new
```

### Test 4: Registry Reset
```bash
rm ~/.pflow/registry.json
uv run pflow "test"  # Should trigger full sync
```

## Performance Expectations

| Scenario | Current (always sync) | With Smart Sync |
|----------|----------------------|-----------------|
| No changes | 3-10 seconds | ~1ms |
| Config changed | 3-10 seconds | 3-10 seconds |
| Typical usage (99% unchanged) | 3-10s every run | ~1ms most runs |

## Implementation Order

1. ✅ Check if Registry has metadata support (might already exist)
2. ✅ Implement smart sync in `_auto_discover_mcp_servers()`
3. ✅ Update manual sync command to set metadata
4. ✅ Test all scenarios
5. ✅ Add logging for debugging (at debug level)

## Rollback Plan

If issues arise:
1. Remove metadata checks
2. Revert to always-sync behavior
3. Or make it opt-in with a flag: `--smart-sync`

## Success Criteria

- [ ] Zero overhead when config unchanged
- [ ] Automatic sync when config changes
- [ ] Handles server renames correctly (no orphaned entries)
- [ ] No manual sync required for normal use
- [ ] Clear logging for debugging
- [ ] Graceful error handling