# Content Pipeline

Read, backup, process, validate, save, and archive content files
with a full audit trail of validation reports.

## Steps

### read_source

Read the source content file for processing.

- type: read-file
- file_path: ${source_dir}/${source_file}

### backup_original

Create a timestamped backup of the original file before any processing.

- type: copy-file
- source: ${source_dir}/${source_file}
- destination: backups/${timestamp_}${source_file}

### process_content

Process the content through the transformation pipeline.

- type: test

### validate_result

Validate the processed content meets quality standards.

- type: test-structured

### save_processed

Save the processed content to the output directory.

- type: write-file
- file_path: processed/${output_file}

### save_validation_report

Write a validation report for audit purposes.

- type: write-file
- file_path: reports/validation_${timestamp.txt}

### retry_processing

Retry processing if validation found issues.

- type: test-retry

### archive_results

Move the processed file to the date-organized archive.

- type: move-file
- source: processed/${output_file}
- destination: archive/${date}/${output_file}
