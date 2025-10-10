# Task 82: Code Examples for Binary Support Implementation

## HTTP Node Implementation

### File: `src/pflow/nodes/http/http.py`

#### Update exec() method (around line 115-145):

```python
import base64

def exec(self, prep_res: tuple[str, str, Optional[dict], Optional[Any], Optional[dict]]) -> dict[str, Any]:
    """Execute the HTTP request."""
    url, method, headers, data, params = prep_res

    try:
        # Make request (existing code)
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=data if method in ["POST", "PUT", "PATCH"] and data else None,
            params=params,
            timeout=30
        )

        # Binary detection (NEW)
        content_type = response.headers.get("content-type", "").lower()
        BINARY_CONTENT_TYPES = [
            "image/", "video/", "audio/",
            "application/pdf", "application/octet-stream",
            "application/zip", "application/gzip", "application/x-tar"
        ]
        is_binary = any(ct in content_type for ct in BINARY_CONTENT_TYPES)

        # Parse response based on type
        if is_binary:
            # Binary response - return raw bytes
            response_data = response.content  # bytes
        elif "json" in content_type:
            # JSON response (existing)
            try:
                response_data = response.json()
            except (ValueError, json.JSONDecodeError):
                response_data = response.text
        else:
            # Text response (existing)
            response_data = response.text

        return {
            "response": response_data,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "duration": response.elapsed.total_seconds(),
            "is_binary": is_binary  # Pass to post()
        }

    except requests.RequestException as e:
        # Existing error handling
        raise
```

#### Update post() method (around line 168-174):

```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store results and determine action."""

    # Handle binary encoding (NEW)
    response_data = exec_res["response"]
    is_binary = exec_res.get("is_binary", False)

    if is_binary:
        # Encode binary data as base64
        encoded = base64.b64encode(response_data).decode('ascii')
        shared["response"] = encoded
        shared["response_is_binary"] = True
    else:
        # Store text/JSON as-is
        shared["response"] = response_data
        shared["response_is_binary"] = False

    # Store other metadata (existing)
    shared["status_code"] = exec_res["status_code"]
    shared["response_headers"] = exec_res["headers"]
    shared["response_time"] = exec_res.get("duration", 0)

    # Existing action logic
    if exec_res["status_code"] >= 400:
        return "error"
    return "default"
```

#### Update Interface documentation:

```python
"""
HTTP node for making web requests.

Interface:
- Reads: shared["url"]: str  # URL to request
- Reads: shared["method"]: str  # HTTP method (GET, POST, etc.)
- Reads: shared["headers"]: dict  # Optional headers
- Reads: shared["body"]: dict|str  # Optional body
- Reads: shared["params"]: dict  # Optional query parameters
- Writes: shared["response"]: str  # Response data (text or base64-encoded binary)
- Writes: shared["response_is_binary"]: bool  # True if response is binary
- Writes: shared["status_code"]: int  # HTTP status code
- Writes: shared["response_headers"]: dict  # Response headers
- Writes: shared["response_time"]: float  # Request duration
- Actions: default (success), error (4xx/5xx)
"""
```

---

## Write-File Node Implementation

### File: `src/pflow/nodes/file/write_file.py`

#### Update prep() method (around line 65-83):

```python
import base64

def prep(self, shared: dict[str, Any]) -> tuple[Any, str, str, bool]:
    """Prepare file writing parameters."""

    # Get parameters (existing)
    content = shared.get("content", self.params.get("content", ""))
    file_path = shared.get("file_path", self.params.get("file_path"))
    encoding = shared.get("encoding", self.params.get("encoding", "utf-8"))
    append = shared.get("append", self.params.get("append", False))

    # Check for binary flag (NEW)
    is_binary = shared.get("content_is_binary", self.params.get("content_is_binary", False))

    if is_binary and isinstance(content, str):
        # Decode base64 to bytes
        try:
            content = base64.b64decode(content)
        except Exception as e:
            # Invalid base64
            raise ValueError(f"Invalid base64 content: {str(e)[:100]}")

    if not file_path:
        raise ValueError("file_path is required")

    # Return with binary indicator
    return (content, str(file_path), encoding, append, is_binary)
```

#### Update exec() method (around line 118-157):

```python
def exec(self, prep_res: tuple) -> str:
    """Write content to file."""
    content, file_path, encoding, append, is_binary = prep_res

    try:
        # Create parent directories if needed (existing)
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)

        if is_binary:
            # Binary write mode (NEW)
            mode = "ab" if append else "wb"
            with open(file_path, mode) as f:
                if isinstance(content, bytes):
                    f.write(content)
                else:
                    # Shouldn't happen if prep() worked correctly
                    raise TypeError(f"Expected bytes for binary write, got {type(content)}")
        else:
            # Text write mode (existing)
            mode = "a" if append else "w"
            with open(file_path, mode, encoding=encoding) as f:
                f.write(str(content))

        return f"File written: {file_path}"

    except Exception as e:
        raise IOError(f"Failed to write file {file_path}: {e}")
```

---

## Read-File Node Implementation

### File: `src/pflow/nodes/file/read_file.py`

#### Update exec() method (around line 67-112):

```python
import base64
from pathlib import Path

def exec(self, prep_res: tuple[str, int, int, str]) -> Any:
    """Read file content."""
    file_path, start_line, max_lines, encoding = prep_res

    # Binary detection (NEW)
    BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico',
                         '.pdf', '.zip', '.tar', '.gz', '.7z', '.rar',
                         '.mp3', '.mp4', '.wav', '.avi', '.mov',
                         '.exe', '.dll', '.so', '.dylib'}

    path = Path(file_path)
    file_ext = path.suffix.lower()
    is_binary = file_ext in BINARY_EXTENSIONS

    try:
        if is_binary:
            # Read as binary (NEW)
            content = path.read_bytes()
            # Store for post() to encode
            self._is_binary = True
            return content
        else:
            # Try text read first (existing logic)
            try:
                lines = path.read_text(encoding=encoding).splitlines()

                # Apply line filtering (existing)
                if start_line > 1:
                    lines = lines[start_line - 1:]
                if max_lines and max_lines > 0:
                    lines = lines[:max_lines]

                # Format with line numbers (existing)
                start_num = start_line
                numbered_lines = []
                for i, line in enumerate(lines, start=start_num):
                    numbered_lines.append(f"{i:6d}\t{line}\n")

                content = "".join(numbered_lines)
                self._is_binary = False
                return content

            except UnicodeDecodeError:
                # File is actually binary despite extension (NEW)
                content = path.read_bytes()
                self._is_binary = True
                return content

    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {file_path}")
    except Exception as e:
        raise IOError(f"Failed to read file {file_path}: {e}")
```

#### Update post() method (around line 134-141):

```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: Any) -> str:
    """Store the file content."""

    if hasattr(self, '_is_binary') and self._is_binary:
        # Encode binary content as base64 (NEW)
        encoded = base64.b64encode(exec_res).decode('ascii')
        shared["content"] = encoded
        shared["content_is_binary"] = True
    else:
        # Store text content as-is (existing)
        shared["content"] = exec_res
        shared["content_is_binary"] = False

    # Store metadata (existing)
    shared["file_path"] = prep_res[0]

    return "default"
```

---

## Shell Node Implementation

### File: `src/pflow/nodes/shell/shell.py`

#### Update exec() method (around line 425-487):

```python
import base64

def exec(self, prep_res: tuple) -> dict[str, Any]:
    """Execute the shell command."""
    command, cwd, env, stdin, timeout = prep_res

    try:
        # Run command (modified for binary handling)
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            input=stdin,
            capture_output=True,  # Get bytes
            text=False,  # CHANGED: Don't decode automatically
            timeout=timeout
        )

        # Handle stdout (NEW binary detection)
        try:
            stdout = result.stdout.decode('utf-8')
            stdout_is_binary = False
        except UnicodeDecodeError:
            # Binary output - will encode in post()
            stdout = result.stdout  # Keep as bytes
            stdout_is_binary = True

        # Handle stderr (always try text for errors)
        try:
            stderr = result.stderr.decode('utf-8')
            stderr_is_binary = False
        except UnicodeDecodeError:
            # Even error output is binary
            stderr = result.stderr
            stderr_is_binary = True

        return {
            "stdout": stdout,
            "stdout_is_binary": stdout_is_binary,
            "stderr": stderr,
            "stderr_is_binary": stderr_is_binary,
            "exit_code": result.returncode
        }

    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Command timed out after {timeout} seconds")
    except Exception as e:
        raise RuntimeError(f"Command execution failed: {e}")
```

#### Update post() method (around line 516-524):

```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store command results."""

    # Handle stdout
    if exec_res["stdout_is_binary"]:
        # Encode binary stdout as base64
        encoded = base64.b64encode(exec_res["stdout"]).decode('ascii')
        shared["stdout"] = encoded
        shared["stdout_is_binary"] = True
    else:
        shared["stdout"] = exec_res["stdout"]
        shared["stdout_is_binary"] = False

    # Handle stderr
    if exec_res["stderr_is_binary"]:
        # Encode binary stderr as base64
        encoded = base64.b64encode(exec_res["stderr"]).decode('ascii')
        shared["stderr"] = encoded
        shared["stderr_is_binary"] = True
    else:
        shared["stderr"] = exec_res["stderr"]
        shared["stderr_is_binary"] = False

    # Store exit code (existing)
    shared["exit_code"] = exec_res["exit_code"]

    # Determine action (existing)
    if exec_res["exit_code"] != 0:
        return "error"
    return "default"
```

---

## Complete Test Suite

### File: `tests/test_nodes/test_binary_support.py`

```python
import base64
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import timedelta
import pytest

from pflow.nodes.http import HttpNode
from pflow.nodes.file import WriteFileNode, ReadFileNode
from pflow.nodes.shell import ShellNode


class TestBinarySupport:
    """Test binary data handling across all nodes."""

    # Test data
    PNG_HEADER = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
    PNG_BASE64 = base64.b64encode(PNG_HEADER).decode('ascii')

    def test_http_binary_download(self):
        """Test HTTP node detects and encodes binary response."""
        with patch("requests.request") as mock_request:
            # Setup mock
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/png"}
            mock_response.content = self.PNG_HEADER
            mock_response.text = "corrupted text"
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            # Run node
            node = HttpNode()
            shared = {"url": "https://example.com/image.png", "method": "GET"}
            action = node.run(shared)

            # Verify
            assert action == "default"
            assert shared["response"] == self.PNG_BASE64
            assert shared["response_is_binary"] is True
            assert shared["status_code"] == 200

    def test_write_file_binary_decode(self):
        """Test write-file decodes base64 and writes binary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.png"

            # Setup shared with base64 data
            shared = {
                "content": self.PNG_BASE64,
                "content_is_binary": True,
                "file_path": str(file_path)
            }

            # Run node
            node = WriteFileNode()
            action = node.run(shared)

            # Verify
            assert action == "default"
            assert file_path.exists()
            assert file_path.read_bytes() == self.PNG_HEADER

    def test_read_file_binary_encode(self):
        """Test read-file detects and encodes binary files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.png"
            file_path.write_bytes(self.PNG_HEADER)

            # Run node
            shared = {"file_path": str(file_path)}
            node = ReadFileNode()
            action = node.run(shared)

            # Verify
            assert action == "default"
            assert shared["content"] == self.PNG_BASE64
            assert shared["content_is_binary"] is True

    def test_shell_binary_stdout(self):
        """Test shell node handles binary output."""
        # Command that outputs binary
        shared = {
            "command": f"echo -ne '\\x89PNG\\r\\n\\x1a\\n'"
        }

        node = ShellNode()
        action = node.run(shared)

        # Verify (approximately - echo might vary)
        assert action == "default"
        assert shared["stdout_is_binary"] is True
        assert shared["exit_code"] == 0
        # Base64 content will vary by platform

    def test_backward_compatibility_text(self):
        """Test text workflows still work without binary flags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"

            # No binary flag - should write as text
            shared = {
                "content": "Hello, World!",
                "file_path": str(file_path)
                # Note: no content_is_binary flag
            }

            node = WriteFileNode()
            action = node.run(shared)

            assert action == "default"
            assert file_path.read_text() == "Hello, World!"

    def test_mixed_binary_text_workflow(self):
        """Test workflow with both binary and text data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write text file
            text_path = Path(tmpdir) / "text.txt"
            shared_text = {
                "content": "Text content",
                "content_is_binary": False,
                "file_path": str(text_path)
            }

            # Write binary file
            binary_path = Path(tmpdir) / "binary.png"
            shared_binary = {
                "content": self.PNG_BASE64,
                "content_is_binary": True,
                "file_path": str(binary_path)
            }

            node = WriteFileNode()

            # Both should work
            assert node.run(shared_text) == "default"
            assert node.run(shared_binary) == "default"

            # Verify content
            assert text_path.read_text() == "Text content"
            assert binary_path.read_bytes() == self.PNG_HEADER

    def test_invalid_base64_error(self):
        """Test clear error on invalid base64."""
        shared = {
            "content": "not-valid-base64!@#$",
            "content_is_binary": True,
            "file_path": "/tmp/test.bin"
        }

        node = WriteFileNode()
        with pytest.raises(ValueError, match="Invalid base64"):
            node.run(shared)
```

---

## Integration Test for Spotify Workflow

### File: `tests/test_integration/test_spotify_workflow.py`

```python
def test_spotify_art_workflow():
    """Test the actual Spotify workflow that was failing."""

    with patch("requests.request") as mock_request:
        # Mock the Replicate API response
        replicate_response = Mock()
        replicate_response.status_code = 200
        replicate_response.headers = {"content-type": "application/json"}
        replicate_response.json.return_value = {
            "output": ["https://replicate.delivery/pbxt/test/out-0.png"],
            "status": "succeeded"
        }

        # Mock the image download
        image_response = Mock()
        image_response.status_code = 200
        image_response.headers = {"content-type": "image/png"}
        image_response.content = PNG_HEADER

        # Route requests based on URL
        def route_request(method, url, **kwargs):
            if "replicate.com" in url:
                return replicate_response
            else:
                return image_response

        mock_request.side_effect = route_request

        # Load and run workflow
        workflow_path = ".pflow/workflows/spotify-art-generator.json"
        # ... run workflow with mocked requests ...

        # Verify images saved correctly
        # ... assertions ...
```

---

## Key Testing Considerations

1. **Always test both paths**: Binary and text in same test file
2. **Mock at requests level**: Not at node level for integration tests
3. **Use real subprocess**: For shell tests (be careful with commands)
4. **Test large files**: At least one test with 10MB+ file
5. **Test edge cases**: Empty files, missing flags, invalid base64
6. **Verify exact bytes**: Use `assert file.read_bytes() == expected_bytes`

---

## Debugging Tips

If binary support isn't working:

1. **Check shared store**: Print `shared` dict to see actual values
2. **Verify base64**: Decode manually to check encoding is correct
3. **Check flags**: Ensure `_is_binary` flags are set correctly
4. **Trace execution**: Use `--trace` flag to see data flow
5. **Test in isolation**: Test each node separately first

---

**Remember**: The goal is to make binary data "just work" transparently while maintaining full backward compatibility with existing text workflows.