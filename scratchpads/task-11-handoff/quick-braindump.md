# Task 11 Quick Braindump from Task 4

## CRITICAL: Use BaseNode not Node
```python
from pocketflow import BaseNode  # NOT from pocketflow import Node
```
This wasted 30 minutes debugging. Registry scanner looks for BaseNode inheritance.

## Node pattern that actually works
```python
class ReadFileNode(BaseNode):
    name = 'read-file'  # Set this explicitly

    def prep(self, shared_storage: dict[str, Any]) -> Any:
        # Validate here, fail fast
        if "file_path" not in shared_storage:
            raise ValueError("Missing required input: file_path")
        return None

    def exec(self, prep_result: Any) -> Any:
        # Use self.shared here (NOT shared_storage)
        path = self.shared["file_path"]
        with open(path) as f:
            return f.read()

    def post(self, shared_storage: dict[str, Any], prep_result: Any, exec_result: Any) -> str:
        shared_storage["content"] = exec_result
        return None  # default transition
```

## Shared storage access
- prep() and post() get `shared_storage` as parameter
- exec() uses `self.shared` (PocketFlow sets this)
- Don't mix these up!

## Testing pattern
```python
# Simulate PocketFlow execution
node = ReadFileNode()
shared = {"file_path": "test.txt"}

prep_result = node.prep(shared)
node.shared = shared  # YOU MUST DO THIS in tests
exec_result = node.exec(prep_result)
node.post(shared, prep_result, exec_result)
```

## Edge field format issue
IR examples use "from"/"to" but schema expects "source"/"target". We fixed compiler to accept both. Your nodes don't care about this.

## Simple is better
Don't overthink nodes. PocketFlow does the orchestration. Your nodes just:
1. Check inputs in prep()
2. Do work in exec()
3. Store results in post()

## Module structure matters
```
src/pflow/nodes/file/
├── read_file.py    # class ReadFileNode
├── write_file.py   # class WriteFileNode
etc.
```

## Force flag pattern for destructive ops
```python
if not shared_storage.get("force", False):
    raise ValueError("Destructive operation requires force=True")
```

## Template variables
If you see `$file_path` in params, pass it through unchanged. Compiler handles these.

## Don't create complex parameter systems
Just use shared storage. Check shared first, then self.params as fallback.

That's it. Keep nodes simple, inherit from BaseNode, set name attribute, use the right shared storage access pattern.
