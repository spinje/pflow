# Cookbook Patterns for Subtask 15.1

## Relevant PocketFlow Cookbook Examples

### 1. pocketflow-map-reduce: Directory Reading Pattern
**Location**: `pocketflow/cookbook/pocketflow-map-reduce/nodes.py`

**Pattern**: Reading multiple files from a directory
```python
def exec(self, _):
    resume_files = {}
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    for filename in os.listdir(data_dir):
        if filename.endswith(".txt"):
            file_path = os.path.join(data_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                resume_files[filename] = file.read()

    return resume_files
```

**Application**: Adapt for JSON files with `.json` extension and parse instead of read

### 2. pocketflow-structured-output: Validation Pattern
**Location**: `pocketflow/cookbook/pocketflow-structured-output/main.py`

**Pattern**: Structured validation with clear error messages
```python
# Validation with assertions
assert structured_result is not None, "Validation Failed: Parsed YAML is None"
assert "name" in structured_result, "Validation Failed: Missing 'name'"
assert isinstance(structured_result.get("experience"), list), "Validation Failed: 'experience' is not a list"
```

**Application**: Use for validating workflow metadata fields

### 3. pocketflow-tool-database: Utility Separation
**Location**: `pocketflow/cookbook/pocketflow-tool-database/tools/database.py`

**Pattern**: Clean separation of utility functions
```python
def execute_sql(query: str, params: Tuple = None) -> List[Tuple[Any, ...]]:
    conn = sqlite3.connect("example.db")
    try:
        cursor = conn.cursor()
        # ... operation ...
        return result
    finally:
        conn.close()
```

**Application**: Create separate utility function for workflow loading logic

## How These Apply to Task 15.1

1. **Directory iteration**: Use os.listdir() pattern but with Path objects
2. **File filtering**: Check for .json extension before processing
3. **Error handling**: Wrap individual file operations in try/except
4. **Validation**: Check required fields with clear error messages
5. **Clean architecture**: Keep loading logic separate from context builder
