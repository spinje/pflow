# Scripts Directory

This directory contains utility scripts for development and testing.

## populate_registry.py

**Status**: TEMPORARY - Will be removed after Task 10

This script manually populates the node registry by scanning the `src/pflow/nodes/` directory. It's a temporary solution for MVP development until proper CLI commands are implemented in Task 10.

### Usage
```bash
python scripts/populate_registry.py
```

### When to use
- Before testing Task 3 implementation
- After adding new nodes during development
- When `~/.pflow/registry.json` doesn't exist

### Future replacement
In Task 10, this will be replaced by proper CLI commands:
- `pflow registry scan` - Scan and populate registry
- `pflow registry list` - List registered nodes
- `pflow registry describe <node>` - Show node details

### Notes
- Only scans `src/pflow/nodes/` directory
- Creates/updates `~/.pflow/registry.json`
- Safe to run multiple times
- Shows what nodes were discovered
