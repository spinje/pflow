# File Processing Pipeline Example

## Purpose
This advanced example demonstrates a complete file processing pipeline with validation and archival. It shows:
- Multi-stage file processing with backup and validation
- Revision loops for retry logic
- Complex file operations workflow
- Integration of multiple test nodes for processing steps

## Use Case
Automated file processing for:
- Data file validation and transformation
- Backup and archival workflows
- Processing with validation loops
- File organization systems

## Visual Flow
```
┌────────────┐    ┌───────────────┐    ┌────────────────┐
│read_source │───►│backup_original│───►│process_content │
└────────────┘    └───────────────┘    └───────┬────────┘
                                                    │
                                                    ▼
                                            ┌────────────────┐
                                            │validate_result │
                                            └───┬─────┬─────┘
                                              │       │
                                         (default) (needs_revision)
                                              │       │
                                              ▼       ▼
                                    ┌──────────────┐ ┌────────────────┐
                                    │save_processed│ │retry_processing│
                                    └─────┬───────┘ └────────┬───────┘
                                          │                     │
                                          ▼                     │
                              ┌──────────────────────┐       │
                              │save_validation_report│◄───────┘
                              └──────────┬──────────┘
                                          │
                                          ▼
                                    ┌───────────────┐
                                    │archive_results│
                                    └───────────────┘
```

## Template Variables
**Configuration Variables**:
- `$source_dir`: Directory containing source files
- `$source_file`: File to process
- `$output_file`: Name for processed output
- `$timestamp`: Current timestamp for backups
- `$date`: Current date for archival

**Data Flow Variables** (set by nodes):
- File content flows through shared store
- Processing results from test nodes
- Validation status determines flow path

## Node Pipeline

### 1. read_source
Reads the source file content into the shared store.

### 2. backup_original
Creates a timestamped backup copy before processing.

### 3. process_content
Processes the file content using test node logic.

### 4. validate_result
Validates the processed content using structured test logic.

### 5. retry_processing
Retry logic for failed validations.

### 6. save_processed
Saves the successfully processed content.

### 7. save_validation_report
Creates a validation report for audit trail.

### 8. archive_results
Moves completed files to dated archive folders.

## Revision Loop
The `validate_result → retry_processing` edge with action "needs_revision" creates a retry loop, ensuring content passes validation before proceeding.

## Pattern Application
This example demonstrates advanced patterns:
1. **Backup Phase**: Ensure data safety before processing
2. **Processing Phase**: Transform content with validation
3. **Archive Phase**: Organize results systematically

Each phase builds on the previous, with data flowing through the shared store.

## How to Run
```python
from pflow.core import validate_ir
import json

with open('content-pipeline.json') as f:
    ir = json.load(f)
    validate_ir(ir)

# Runtime parameters:
params = {
    "source_dir": "/data/incoming",
    "source_file": "data.csv",
    "output_file": "processed_data.csv",
    "timestamp": "2024-01-15_143022",
    "date": "2024-01-15"
}
```

## Extending This Workflow
1. **Multiple file types**: Add nodes for different file formats
2. **Parallel processing**: Process multiple files simultaneously
3. **Compression**: Add compression before archival
4. **Cloud backup**: Direct integration with cloud storage

## Key Insights
- Sequential processing ensures data integrity
- Revision loops maintain quality through validation
- Template variables enable reuse for any file type
- File operations provide reliable data handling
