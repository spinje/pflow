# Template Variables

Demonstrates the ${var} template syntax for passing data between nodes
and referencing workflow inputs. Variables appear in file paths, API
endpoints, email subjects, and multi-line content strings — showing
how a single workflow adapts to different inputs at runtime.

## Steps

### reader

Read the input file specified by template variables. Both the file
path and encoding are configurable at runtime.

- type: read-file
- file_path: ${input_file}
- encoding: ${file_encoding}

### api_caller

Call an external API endpoint with authentication. The endpoint URL
and auth token are resolved from workflow inputs.

- type: shell

```shell command
curl -s -H "Authorization: Bearer ${api_token}" "${api_endpoint}"
```

### copier

Copy the input file to the backup directory with a custom name.
Demonstrates template variables in path construction.

- type: copy-file
- source_path: ${input_file}
- dest_path: ${backup_dir}/${backup_name}

### writer

Write a timestamped output file that includes the original file content.
Shows template variables embedded in multi-line content strings.

- type: write-file
- file_path: ${output_dir}/${output_file}
- content: "Processed on: ${timestamp}\nOriginal file: ${input_file}\n\n${file_content}"

### notifier

Send a notification email when processing completes. Template variables
work in any string value, including email subjects.

- type: shell

```shell command
echo "Notification: Process completed for ${input_file} — sent to ${recipient_email}"
```
