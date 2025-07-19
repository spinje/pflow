# Template Variables Example

## Purpose
This example demonstrates the use of template variables (`$variable` syntax) throughout an IR. It shows:
- Variables in different contexts (URLs, headers, paths, text)
- How variables enable dynamic, reusable workflows
- Variables referencing both input parameters and runtime values

## Use Case
Template variables are essential for:
- Configurable workflows that adapt to different environments
- Reusable workflows with different inputs
- Dynamic file paths and directories
- Configurable file operations

## Visual Flow
```
[reader: read-file] → [copier: copy-file] → [writer: write-file]
        ↓                     ↓                      ↓
   $input_file          $backup_dir           $output_dir
  $file_encoding       $backup_name          $output_file
                                            $timestamp
```

## Template Variables Used
- **$input_file**: Source file path to read
- **$file_encoding**: Character encoding for reading
- **$backup_dir**: Directory for backup copies
- **$backup_name**: Name for the backup file
- **$output_dir**: Directory for output files
- **$output_file**: Name for the output file
- **$timestamp**: Runtime value for when processed
- **$file_content**: Content read from the file

## Node Explanation
1. **reader**: Reads file content
   - Uses variables for file path and encoding

2. **copier**: Creates a backup copy
   - Configurable source and destination paths

3. **writer**: Writes processed content
   - Combines static text with file content and metadata

## How Variables Are Resolved
Variables are resolved at runtime from:
1. Initial workflow parameters
2. Shared store values set by nodes
3. System-provided values (like $timestamp)

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('template-variables.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Variables are valid strings

# At runtime, you'd provide values:
# params = {
#     "input_file": "/data/input.txt",
#     "file_encoding": "utf-8",
#     "backup_dir": "/backups",
#     "backup_name": "input_backup.txt",
#     "output_dir": "/processed",
#     "output_file": "output.txt"
# }
```

## Common Variations
1. **Nested variables**: `"path": "/users/$user_id/posts/$post_id"`
2. **Mixed content**: `"message": "Hello $name, your order #$order_id is ready"`
3. **Conditional defaults**: Different default values based on context
4. **Variable interpolation**: Building complex strings from multiple variables

## Notes
- Variables are treated as literal strings during validation
- The $ prefix is the only special syntax recognized
- Variables can appear anywhere a string value is expected
- Resolution happens at runtime, not during IR validation
