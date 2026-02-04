# File Migration

Migrate files between directories following a manifest, with backup,
reporting, cleanup, and error logging.

## Steps

### read_manifest

Read the migration manifest describing which files to move.

- type: read-file
- file_path: ${migration_dir}/manifest.json

### backup_destination

Back up the destination directory before overwriting anything.

- type: copy-file
- source: ${destination_dir}
- destination: ${backup_dir}/${timestamp_destination}

### process_files

Process the file list from the manifest.

- type: test

### copy_new_files

Copy each new file to the destination directory.

- type: copy-file
- source: ${source_dir}/${current_file}
- destination: ${destination_dir}/${current_file}

### move_old_files

Move superseded files to the archive directory.

- type: move-file
- source: ${destination_dir}/${old_file}
- destination: ${archive_dir}/${old_file}

### cleanup_temp

Remove temporary files created during the migration.

- type: delete-file
- file_path: ${temp_dir}/${temp_file}

### write_report

Write a summary report of the migration results.

- type: write-file
- file_path: ${reports_dir}/migration_${timestamp.log}
- content: "Migration completed at ${timestamp}\nFiles copied: ${copied_count}\nFiles moved: ${moved_count}\nErrors: ${error_count}"

### handle_error

Log errors that occur during migration for later investigation.

- type: write-file
- file_path: ${logs_dir}/error_${timestamp.log}
- content: "Error during migration: ${error_message}\nTimestamp: ${timestamp}\nCurrent operation: ${current_operation}"
- append: true
