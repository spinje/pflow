# File Migration

Migrate files between directories following a manifest, with backup,
reporting, cleanup, and error logging.

> **Structural demo, not a runnable pipeline.** Several inputs below
> (`copied_count`, `moved_count`, `error_count`, `error_message`,
> `current_operation`) are declared as workflow inputs with defaults
> so the file validates, but in a real workflow these would flow from
> earlier node outputs (`${process_files.stdout}`, etc.). Treat this
> file as a layout reference for multi-step file operations, not a
> template to copy verbatim.

## Inputs

### migration_dir

Directory containing the migration manifest.

- type: string
- required: true

### destination_dir

Directory that new files are copied into.

- type: string
- required: true

### backup_dir

Directory used to back up the destination before the migration.

- type: string
- required: true

### source_dir

Directory containing the new files.

- type: string
- required: true

### archive_dir

Directory that superseded files are moved into.

- type: string
- required: true

### temp_dir

Directory holding temporary files that must be cleaned up.

- type: string
- default: /tmp

### reports_dir

Directory where the migration report is written.

- type: string
- default: ./reports

### logs_dir

Directory where migration errors are logged.

- type: string
- default: ./logs

### timestamp

Timestamp used in backup, report, and log filenames.

- type: string
- default: "unknown"

### timestamp_destination

Timestamp-based directory name used under backup_dir for this run.

- type: string
- default: "unknown"

### current_file

Filename in source_dir to copy during this run.

- type: string
- required: true

### old_file

Filename in destination_dir to archive during this run.

- type: string
- required: true

### temp_file

Filename to remove from temp_dir during cleanup.

- type: string
- required: true

### copied_count

Number of files copied — typically supplied by an outer pipeline.

- type: integer
- default: 0

### moved_count

Number of files moved — typically supplied by an outer pipeline.

- type: integer
- default: 0

### error_count

Number of errors observed — typically supplied by an outer pipeline.

- type: integer
- default: 0

### error_message

Message recorded by the error handler.

- type: string
- default: ""

### current_operation

Name of the operation that triggered the error.

- type: string
- default: ""

## Steps

### read_manifest

Read the migration manifest describing which files to move.

- type: read-file
- file_path: ${migration_dir}/manifest.json

### backup_destination

Back up the destination directory before overwriting anything.

- type: copy-file
- source_path: ${destination_dir}
- dest_path: ${backup_dir}/${timestamp_destination}

### process_files

Process the file list from the manifest.

- type: shell

```shell command
echo "Processing file list from manifest..."
```

### copy_new_files

Copy each new file to the destination directory.

- type: copy-file
- source_path: ${source_dir}/${current_file}
- dest_path: ${destination_dir}/${current_file}

### move_old_files

Move superseded files to the archive directory.

- type: move-file
- source_path: ${destination_dir}/${old_file}
- dest_path: ${archive_dir}/${old_file}

### cleanup_temp

Remove temporary files created during the migration.

- type: delete-file
- file_path: ${temp_dir}/${temp_file}

### write_report

Write a summary report of the migration results.

- type: write-file
- file_path: ${reports_dir}/migration_${timestamp}.log
- content: "Migration completed at ${timestamp}\nFiles copied: ${copied_count}\nFiles moved: ${moved_count}\nErrors: ${error_count}"

### handle_error

Log errors that occur during migration for later investigation.

- type: write-file
- file_path: ${logs_dir}/error_${timestamp}.log
- content: "Error during migration: ${error_message}\nTimestamp: ${timestamp}\nCurrent operation: ${current_operation}"
- append: true
