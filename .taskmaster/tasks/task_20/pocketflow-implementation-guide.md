# Task 20: Lockfile and Plan Storage - PocketFlow Implementation Guide

## Overview
This task implements the persistence layer for pflow, managing workflow plans, lockfiles, and execution history. PocketFlow orchestrates the storage operations with proper error handling, atomic writes, and migration support.

## PocketFlow Architecture

### Flow Structure
```
StorageOperation >> ValidateData >> CheckConflicts >> WriteAtomic >> UpdateIndex >> Success
        |                |               |                |              |
        v                v               v                v              v
   ParseError      ValidationError  ConflictError   WriteError    IndexError
                                         |
                                         v
                                   ResolveConflict
```

### Key Nodes

#### 1. WorkflowStorageNode
```python
class WorkflowStorageNode(Node):
    """Store workflow with atomic write and backup"""
    def __init__(self, storage_path):
        super().__init__(max_retries=3, wait=1)
        self.storage_path = Path(storage_path)

    def exec(self, shared):
        workflow = shared["workflow_to_store"]
        workflow_id = shared["workflow_id"]

        # Prepare storage location
        workflow_dir = self.storage_path / workflow_id
        workflow_dir.mkdir(parents=True, exist_ok=True)

        # Store with atomic write
        workflow_file = workflow_dir / "workflow.json"
        lockfile = workflow_dir / "workflow.lock"

        # Check for existing lockfile
        if lockfile.exists():
            shared["existing_lock"] = self._read_lockfile(lockfile)
            return "handle_conflict"

        # Write atomically
        temp_file = workflow_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(workflow, f, indent=2)

            # Atomic rename
            temp_file.replace(workflow_file)

            # Create lockfile
            self._write_lockfile(lockfile, workflow)

            shared["stored_path"] = str(workflow_file)
            return "update_index"

        except Exception as e:
            shared["storage_error"] = str(e)
            temp_file.unlink(missing_ok=True)
            return "write_error"
```

#### 2. LockfileManagerNode
```python
class LockfileManagerNode(Node):
    """Manage workflow lockfiles with conflict resolution"""
    def exec(self, shared):
        operation = shared["lock_operation"]

        if operation == "acquire":
            return self._acquire_lock(shared)
        elif operation == "release":
            return self._release_lock(shared)
        elif operation == "check":
            return self._check_lock(shared)
        else:
            shared["error"] = f"Unknown lock operation: {operation}"
            return "error"

    def _acquire_lock(self, shared):
        lockfile_path = Path(shared["lockfile_path"])
        workflow_hash = shared["workflow_hash"]

        # Check if lock exists
        if lockfile_path.exists():
            existing_lock = self._read_lock(lockfile_path)

            if existing_lock["hash"] == workflow_hash:
                # Same workflow, allow
                return "already_locked"
            else:
                # Different workflow, conflict
                shared["lock_conflict"] = existing_lock
                return "conflict"

        # Create lock
        lock_data = {
            "hash": workflow_hash,
            "timestamp": datetime.now().isoformat(),
            "pid": os.getpid(),
            "host": socket.gethostname()
        }

        # Atomic write
        self._atomic_write(lockfile_path, lock_data)
        shared["lock_acquired"] = True
        return "success"
```

#### 3. StorageIndexNode
```python
class StorageIndexNode(Node):
    """Maintain searchable index of stored workflows"""
    def __init__(self, index_path):
        super().__init__(max_retries=3)
        self.index_path = Path(index_path)

    def exec(self, shared):
        workflow_id = shared["workflow_id"]
        metadata = shared["workflow_metadata"]

        # Load existing index
        index = self._load_index()

        # Update index
        index[workflow_id] = {
            "name": metadata.get("name", "Unnamed"),
            "description": metadata.get("description", ""),
            "created": datetime.now().isoformat(),
            "nodes": [n["type"] for n in metadata.get("nodes", [])],
            "tags": metadata.get("tags", []),
            "hash": shared.get("workflow_hash"),
            "path": shared["stored_path"]
        }

        # Save atomically
        self._save_index(index)
        shared["index_updated"] = True
        return "success"

    def _save_index(self, index):
        """Atomic index save with backup"""
        temp_file = self.index_path.with_suffix('.tmp')
        backup_file = self.index_path.with_suffix('.bak')

        # Write to temp
        with open(temp_file, 'w') as f:
            json.dump(index, f, indent=2)

        # Backup existing
        if self.index_path.exists():
            self.index_path.replace(backup_file)

        # Atomic rename
        temp_file.replace(self.index_path)
```

#### 4. ConflictResolutionNode
```python
class ConflictResolutionNode(Node):
    """Handle storage conflicts with user interaction"""
    def __init__(self, ui_handler):
        super().__init__()
        self.ui = ui_handler

    def exec(self, shared):
        conflict_type = shared.get("conflict_type")

        if conflict_type == "lockfile":
            existing = shared["existing_lock"]

            # Check if lock is stale
            if self._is_stale_lock(existing):
                shared["resolution"] = "override_stale"
                return "remove_lock"

            # Ask user
            choice = self.ui.prompt_choice(
                f"Workflow is locked since {existing['timestamp']}",
                ["Wait", "Override", "Cancel"]
            )

            if choice == "Wait":
                shared["resolution"] = "wait"
                return "wait_for_lock"
            elif choice == "Override":
                shared["resolution"] = "override"
                return "remove_lock"
            else:
                shared["resolution"] = "cancelled"
                return "cancelled"

        elif conflict_type == "version":
            return self._handle_version_conflict(shared)
```

## Implementation Plan

### Phase 1: Core Storage
1. Create `src/pflow/flows/storage/` structure
2. Implement atomic file operations
3. Create lockfile management
4. Build basic index system

### Phase 2: Conflict Resolution
1. Detect and classify conflicts
2. Implement resolution strategies
3. Add user interaction flow
4. Create stale lock detection

### Phase 3: Index & Search
1. Build workflow index
2. Add search capabilities
3. Implement tag system
4. Create metadata extraction

### Phase 4: Migration & Backup
1. Version migration system
2. Automatic backups
3. Storage cleanup
4. Export/import flows

## Testing Strategy

### Unit Tests
```python
def test_atomic_write():
    """Test atomic file writing prevents corruption"""
    node = WorkflowStorageNode(temp_dir)

    # Simulate write failure
    with patch('json.dump') as mock_dump:
        mock_dump.side_effect = Exception("Write failed")

        result = node.exec({
            "workflow_to_store": {...},
            "workflow_id": "test"
        })

        assert result == "write_error"
        # Ensure no partial files
        assert not (temp_dir / "test" / "workflow.json").exists()
```

### Integration Tests
```python
def test_concurrent_access():
    """Test lockfile prevents concurrent modifications"""
    flow = create_storage_flow()

    # First process acquires lock
    result1 = flow.run({
        "operation": "store",
        "workflow": workflow1,
        "workflow_id": "shared"
    })
    assert result1["lock_acquired"]

    # Second process detects conflict
    result2 = flow.run({
        "operation": "store",
        "workflow": workflow2,
        "workflow_id": "shared"
    })
    assert result2["conflict_type"] == "lockfile"
```

## Storage Patterns

### Atomic Operations
```python
def _atomic_write(self, path, data):
    """Write atomically using temp file and rename"""
    temp_path = path.with_suffix('.tmp')

    # Write to temp with fsync
    with open(temp_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # Atomic rename (on POSIX)
    temp_path.replace(path)

    # Sync directory (ensure rename is persisted)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
```

### Lockfile Format
```json
{
    "version": "1.0",
    "hash": "sha256:abc123...",
    "timestamp": "2024-01-15T10:30:00Z",
    "pid": 12345,
    "host": "hostname",
    "user": "username",
    "expires": "2024-01-15T11:30:00Z"
}
```

## Benefits of PocketFlow Approach

1. **Automatic Retry**: File operations with built-in retry
2. **Conflict Flow**: Clear paths for different conflicts
3. **Atomic Safety**: All operations are atomic
4. **State Tracking**: Full operation history
5. **Error Recovery**: Graceful handling of failures

## Storage Organization

### Directory Structure
```
.pflow/
├── workflows/
│   ├── workflow-id-1/
│   │   ├── workflow.json
│   │   ├── workflow.lock
│   │   └── metadata.json
│   └── workflow-id-2/
│       └── ...
├── index.json
├── index.bak
└── config.json
```

### Index Schema
```json
{
    "workflow-id": {
        "name": "Process Customer Data",
        "description": "ETL pipeline for customer analytics",
        "created": "2024-01-15T10:30:00Z",
        "modified": "2024-01-15T14:20:00Z",
        "nodes": ["read_file", "transform", "llm", "write_file"],
        "tags": ["etl", "customer", "analytics"],
        "hash": "sha256:def456...",
        "version": "1.2",
        "path": ".pflow/workflows/workflow-id/workflow.json"
    }
}
```

## Performance Optimizations

1. **Index Caching**: Keep index in memory
2. **Lazy Loading**: Load workflows on demand
3. **Batch Operations**: Group multiple stores
4. **Background Sync**: Async index updates

## Migration Support

```python
class MigrationNode(Node):
    """Handle storage format migrations"""
    def exec(self, shared):
        current_version = shared["storage_version"]
        target_version = shared["target_version"]

        if current_version < target_version:
            migrations = self._get_migrations(current_version, target_version)

            for migration in migrations:
                shared["current_migration"] = migration.name
                result = migration.apply(shared)

                if result != "success":
                    return "migration_failed"

            return "migration_complete"

        return "no_migration_needed"
```

## Future Extensions

1. **Cloud Storage**: S3/GCS backends
2. **Encryption**: At-rest encryption
3. **Versioning**: Full history tracking
4. **Sync**: Multi-device synchronization
