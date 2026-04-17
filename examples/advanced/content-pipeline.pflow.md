# Content Pipeline

Read, backup, process, validate, save, and archive content files
with a full audit trail of validation reports.

## Inputs

### source_dir

Directory containing the source file.

- type: string
- required: true

### source_file

Filename of the source content to process.

- type: string
- required: true

### output_file

Filename for the processed content.

- type: string
- required: true

### timestamp

Timestamp used in backup and report filenames.

- type: string
- default: "unknown"

### date

Date folder name used by the archive step.

- type: string
- default: "unknown"

## Steps

### read_source

Read the source content file for processing.

- type: read-file
- file_path: ${source_dir}/${source_file}

### backup_original

Create a timestamped backup of the original file before any processing.

- type: copy-file
- source_path: ${source_dir}/${source_file}
- dest_path: backups/${timestamp}_${source_file}

### process_content

Process the content through the transformation pipeline.

- type: shell

```shell command
echo "Processing content..."
```

### validate_result

Validate the processed content meets quality standards.

- type: shell

```shell command
echo '{"valid": true, "score": 95}'
```

### save_processed

Save the processed content to the output directory.

- type: write-file
- file_path: processed/${output_file}

### save_validation_report

Write a validation report for audit purposes.

- type: write-file
- file_path: reports/validation_${timestamp}.txt

### retry_processing

Retry processing if validation found issues.

- type: shell

```shell command
echo "Retrying processing..."
```

### archive_results

Move the processed file to the date-organized archive.

- type: move-file
- source_path: processed/${output_file}
- dest_path: archive/${date}/${output_file}
