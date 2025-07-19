# File Migration Workflow Example

## Purpose
This advanced example demonstrates a complete file migration workflow. It shows:
- Complex multi-stage file operations
- Backup and recovery procedures
- Error handling with logging
- Cleanup operations

## Use Case
Automated file migration for:
- System upgrades requiring file reorganization
- Data archival workflows
- Backup and restore operations
- Directory structure migrations

## Visual Flow
```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│read_manifest│────►│backup_destination│────►│process_files │
└─────┬───────┘     └────────┬─────────┘     └──────┬────────┘
      │                      │                       │
   (error)                (error)                    ↓
      │                      │                ┌──────────────┐
      ▼                      ▼                │copy_new_files│
┌─────────────┐                              └──────┬────────┘
│handle_error │◄────────────────────────────────(error)
└─────────────┘                                      │
      ▲                                         (success)
      │                                              ↓
      │                                       ┌──────────────┐
      └───────────────────────────────────────│move_old_files│
                          (error)             └──────┬────────┘
                                                     │
                                                (success)
                                                     ↓
                                              ┌──────────────┐
                                              │cleanup_temp  │
                                              └──────┬────────┘
                                                     │
                                                     ↓
                                              ┌──────────────┐
                                              │write_report  │
                                              └──────────────┘
```

## Template Variables
**Input Variables** (provided at workflow start):
- `$migration_dir`: Directory containing migration config
- `$source_dir`: Source directory for new files
- `$destination_dir`: Target directory for migration
- `$backup_dir`: Backup location
- `$archive_dir`: Archive for old files
- `$reports_dir`: Location for reports
- `$logs_dir`: Location for error logs
- `$temp_dir`: Temporary working directory

**Runtime Variables** (set by nodes):
- `$timestamp`: Current timestamp for backups
- `$current_file`: File being processed
- `$old_file`: File to be archived
- `$temp_file`: Temporary file to clean up
- `$copied_count`: Number of files copied
- `$moved_count`: Number of files moved
- `$error_count`: Number of errors encountered
- `$error_message`: Last error message
- `$current_operation`: Operation that failed

## Node Details

### 1. read_manifest
Reads the migration manifest file that contains the list of files to process.

### 2. backup_destination
Creates a backup of the destination directory before making changes.

### 3. process_files
Test node that processes the manifest and prepares file lists.

### 4. copy_new_files
Copies new files from source to destination directory.

### 5. move_old_files
Moves obsolete files from destination to archive directory.

### 6. cleanup_temp
Removes temporary files created during migration.

### 7. write_report
Creates a detailed report of the migration results.

### 8. handle_error
Logs any errors that occur during the migration process.

## Error Handling
Critical operations have error routing to `handle_error`, ensuring all failures are logged for troubleshooting.

## How to Run
```python
# Validate the workflow
from pflow.core import validate_ir
import json

with open('file-migration.json') as f:
    ir = json.load(f)
    validate_ir(ir)

# At runtime, provide:
params = {
    "migration_dir": "/config/migration",
    "source_dir": "/data/new",
    "destination_dir": "/data/current",
    "backup_dir": "/backups",
    "archive_dir": "/archive",
    "reports_dir": "/reports",
    "logs_dir": "/logs",
    "temp_dir": "/tmp"
}
```

## Extending This Workflow
1. **Add verification**: Verify file integrity after copy
2. **Parallel processing**: Process multiple files concurrently
3. **Rollback capability**: Restore from backup on failure
4. **Progress tracking**: Add progress reporting for large migrations

## Implementation Notes
This example demonstrates how pflow can orchestrate complex file operations:
- Sequential processing ensures data safety
- Comprehensive error handling prevents data loss
- Template variables make the workflow reusable
- Cleanup ensures no temporary files remain

The workflow follows best practices for file migrations with proper backup, verification, and reporting.
