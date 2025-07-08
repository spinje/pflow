# Cookbook Patterns for File Node Polish

## Pattern 1: Structured Logging from Cold Email Personalization

**Location**: `/pocketflow/cookbook/Tutorial-Cold-Email-Personalization/flow.py`

### How to Apply:
```python
import logging
import sys

# Setup at module level
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class ReadFileNode(Node):
    def prep(self, shared):
        file_path = self._get_file_path(shared)
        logger.debug("Preparing to read file", extra={"file_path": file_path, "phase": "prep"})
        return file_path

    def exec(self, file_path):
        logger.info("Reading file", extra={"file_path": file_path, "phase": "exec"})
        # ... implementation
        logger.info("File read successfully", extra={
            "file_path": file_path,
            "size_bytes": len(content),
            "phase": "exec"
        })
```

### Benefits:
- Structured logging with phases helps debugging
- Log levels allow filtering in production
- Extra fields enable log analysis

## Pattern 2: exec_fallback for Graceful Degradation

**Inspiration**: Supervisor pattern and core Node documentation

### How to Apply:
```python
class ReadFileNode(Node):
    def __init__(self):
        super().__init__(max_retries=3, wait=0.1)

    def exec_fallback(self, prep_res, exc):
        """Called when all retries are exhausted"""
        file_path = prep_res
        logger.error(f"Failed to read file after {self.max_retries} retries",
                    extra={"file_path": file_path, "error": str(exc), "phase": "fallback"})

        # Return a result that allows the flow to continue
        return (f"Error: Could not read {file_path} - {exc}. "
                f"Please check file permissions and path.", False)
```

### Benefits:
- Provides meaningful feedback when retries fail
- Allows workflows to handle failures gracefully
- Better than generic exception propagation

## Pattern 3: Resource Management from Database Tools

**Location**: `/pocketflow/cookbook/pocketflow-tool-database/tools/database.py`

### How to Apply for Atomic Writes:
```python
import tempfile
import shutil

class WriteFileNode(Node):
    def _atomic_write(self, file_path: str, content: str, encoding: str) -> tuple[str, bool]:
        """Write file atomically using temp file + rename"""
        dir_path = os.path.dirname(file_path)

        # Create temp file in same directory for atomic rename
        temp_fd, temp_path = tempfile.mkstemp(dir=dir_path, text=True)

        try:
            with os.fdopen(temp_fd, 'w', encoding=encoding) as f:
                f.write(content)

            # Atomic rename (on same filesystem)
            shutil.move(temp_path, file_path)
            logger.info("File written atomically", extra={
                "file_path": file_path,
                "temp_path": temp_path,
                "phase": "exec"
            })
            return f"Successfully wrote to {file_path}", True

        except Exception as e:
            # Clean up temp file on failure
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            logger.error("Atomic write failed", extra={
                "file_path": file_path,
                "temp_path": temp_path,
                "error": str(e),
                "phase": "exec"
            })
            raise
```

### Benefits:
- Prevents partial writes and corruption
- Standard pattern for reliable file operations
- Works across platforms

## Pattern 4: Progress Tracking for Large Operations

**Adapted from**: Batch processing patterns

### How to Apply:
```python
def _copy_with_progress(self, source: str, dest: str) -> tuple[str, bool]:
    """Copy file with progress logging for large files"""
    file_size = os.path.getsize(source)

    # Log start for large files
    if file_size > 1024 * 1024:  # 1MB
        logger.info("Starting large file copy", extra={
            "source_path": source,
            "dest_path": dest,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "phase": "exec"
        })

    shutil.copy2(source, dest)

    # Log completion
    logger.info("File copy completed", extra={
        "source_path": source,
        "dest_path": dest,
        "size_bytes": file_size,
        "phase": "exec"
    })
```

### Benefits:
- Users know long operations are progressing
- Helps identify performance bottlenecks
- Useful for debugging timeouts

## Integration Notes

These patterns work together:
1. Structured logging provides visibility
2. exec_fallback handles failures gracefully
3. Atomic operations prevent corruption
4. Progress tracking improves UX

All patterns maintain compatibility with existing Node interfaces and the established tuple return pattern.
