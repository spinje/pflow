"""Integration tests for binary data flow through HTTP → Write → Read pipeline.

Tests the complete binary data contract with workflow compilation, template resolution,
and data integrity verification. This catches integration issues that unit tests miss.
"""

import base64
import hashlib
from datetime import timedelta
from unittest.mock import Mock, patch

from pflow.registry.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


class TestBinaryDataRoundtrip:
    """Test binary data integrity through complete HTTP → Write → Read pipeline."""

    # Real PNG structure (minimal but valid 1x1 black pixel)
    PNG_HEADER = b"\x89PNG\r\n\x1a\n"
    PNG_IHDR = b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x00\x00\x00\x00:\x7e\x9bU"
    PNG_IDAT = b"\x00\x00\x00\nIDAT\x08\x1d\x01\x00\x00\xff\xff\x00\x00\x00\x01"
    PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
    TEST_PNG_BYTES = PNG_HEADER + PNG_IHDR + PNG_IDAT + PNG_IEND

    def test_binary_roundtrip_http_write_read_pipeline(self, tmp_path):
        """Full pipeline: HTTP download → write-file → read-file with binary data.

        Verifies:
        1. HTTP binary detection (Content-Type) and base64 encoding
        2. Template resolution of binary data and flags
        3. Write-file base64 decoding and binary write
        4. Read-file binary detection and base64 encoding
        5. Data integrity through complete pipeline (MD5 match)

        This catches integration issues that unit tests miss:
        - Template variable resolution with binary flags
        - Shared store handoff between nodes (namespacing)
        - Binary data corruption at any stage
        - Registry metadata accuracy for template validation
        """
        # Calculate original MD5 for verification (not for security - for data integrity)
        original_md5 = hashlib.md5(self.TEST_PNG_BYTES).hexdigest()  # noqa: S324

        # Setup temp file path
        temp_file = tmp_path / "test.png"

        # Create workflow IR for HTTP → Write → Read pipeline
        workflow_ir = {
            "name": "test-binary-roundtrip",
            "nodes": [
                {
                    "id": "download",
                    "type": "http",
                    "params": {"url": "https://example.com/test.png", "method": "GET"},
                },
                {
                    "id": "save",
                    "type": "write-file",
                    "params": {
                        "file_path": "${temp_file}",
                        "content": "${download.response}",
                        "content_is_binary": "${download.response_is_binary}",
                    },
                },
                {
                    "id": "verify",
                    "type": "read-file",
                    "params": {"file_path": "${temp_file}"},
                },
            ],
            "edges": [
                {"from": "download", "to": "save", "action": "default"},
                {"from": "save", "to": "verify", "action": "default"},
            ],
            "start_node": "download",
        }

        # Mock HTTP response with binary PNG data
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/png"}
            mock_response.content = self.TEST_PNG_BYTES  # Binary response
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            # Compile workflow with template parameter
            registry = Registry()
            flow = compile_ir_to_flow(
                workflow_ir, registry=registry, initial_params={"temp_file": str(temp_file)}, validate=True
            )

            # Execute workflow
            shared = {}
            flow.run(shared)

        # === Verification Phase ===

        # 1. Verify file was created
        assert temp_file.exists(), "Binary file not created by write-file node"

        # 2. Verify data integrity (THE CRITICAL TEST)
        written_bytes = temp_file.read_bytes()
        written_md5 = hashlib.md5(written_bytes).hexdigest()  # noqa: S324
        assert written_md5 == original_md5, f"Data corruption detected: {written_md5} != {original_md5}"

        # 3. Verify HTTP node set binary flag
        assert shared["download"]["response_is_binary"] is True, "HTTP node didn't set response_is_binary flag"

        # 4. Verify write-file succeeded (written contains success message, not boolean)
        assert "written" in shared["save"], "Write-file node didn't store 'written' key"
        assert shared["save"]["written"], "Write-file node failed (written is falsy)"

        # 5. Verify read-file detected binary and set flag
        assert shared["verify"]["content_is_binary"] is True, "Read-file didn't detect binary"

        # 6. Verify read-back content matches (base64 encoded)
        readback_content = shared["verify"]["content"]
        assert isinstance(readback_content, str), "Read-file didn't return string"

        # Decode and verify
        decoded = base64.b64decode(readback_content)
        assert decoded == self.TEST_PNG_BYTES, "Read-back data doesn't match original"

    def test_text_file_still_works_with_binary_support(self, tmp_path):
        """Verify text files work correctly (backward compatibility).

        Binary support shouldn't break existing text workflows.
        Text files should NOT be base64 encoded.
        """
        # Setup temp file path
        temp_file = tmp_path / "test.txt"
        test_content = "Hello, World!\nThis is a test."

        # Create workflow IR for Write → Read text pipeline
        workflow_ir = {
            "name": "test-text-roundtrip",
            "nodes": [
                {
                    "id": "write",
                    "type": "write-file",
                    "params": {"file_path": "${temp_file}", "content": test_content},
                },
                {
                    "id": "read",
                    "type": "read-file",
                    "params": {"file_path": "${temp_file}"},
                },
            ],
            "edges": [{"from": "write", "to": "read", "action": "default"}],
            "start_node": "write",
        }

        # Compile and execute
        registry = Registry()
        flow = compile_ir_to_flow(
            workflow_ir, registry=registry, initial_params={"temp_file": str(temp_file)}, validate=True
        )

        shared = {}
        flow.run(shared)

        # Verify text handling
        assert temp_file.exists(), "Text file not created"
        assert "written" in shared["write"], "Write-file didn't store 'written' key"
        assert shared["write"]["written"], "Write-file failed (written is falsy)"
        assert shared["read"]["content_is_binary"] is False, "Text file incorrectly detected as binary"

        # Verify content has line numbers (read-file feature)
        content = shared["read"]["content"]
        assert "1: Hello, World!" in content, "Line numbers missing from text file"
        assert "2: This is a test." in content, "Second line missing"

    def test_http_text_response_not_base64_encoded(self, tmp_path):
        """Verify HTTP text responses are NOT base64 encoded.

        This ensures backward compatibility - JSON and text responses
        should remain as-is, not base64 encoded.
        """
        # Create workflow with HTTP request returning JSON
        workflow_ir = {
            "name": "test-http-json",
            "nodes": [
                {
                    "id": "fetch",
                    "type": "http",
                    "params": {"url": "https://api.example.com/data", "method": "GET"},
                }
            ],
            "edges": [],
            "start_node": "fetch",
        }

        # Mock JSON response
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            # Mock response.json() method
            mock_response.json.return_value = {"status": "success", "data": [1, 2, 3]}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            # Compile and execute
            registry = Registry()
            flow = compile_ir_to_flow(workflow_ir, registry=registry, validate=True)

            shared = {}
            flow.run(shared)

        # Verify JSON response is NOT base64 encoded
        assert shared["fetch"]["response_is_binary"] is False, "JSON incorrectly flagged as binary"
        assert isinstance(shared["fetch"]["response"], dict), "JSON not parsed correctly"
        assert shared["fetch"]["response"]["status"] == "success", "JSON content wrong"
