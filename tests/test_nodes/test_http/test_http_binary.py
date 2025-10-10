"""Tests for HTTP node binary data handling.

Each test catches ONE specific bug that would break binary downloads.
These tests protect AI agents from breaking the codebase.
"""

import base64
from datetime import timedelta
from unittest.mock import Mock, patch

from src.pflow.nodes.http import HttpNode


class TestHttpBinarySupport:
    """
    Tests for HTTP node binary data handling.

    Focus: Catch real bugs, not achieve coverage metrics.
    Each test validates one specific behavior that would break workflows if changed.
    """

    # Test data: Real PNG header bytes
    PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00d\x00\x00\x00d"

    def test_binary_detection_for_image_png(self):
        """Catch: image/png not detected as binary → data corruption.

        This is the most common use case (downloading images).
        If this breaks, all image downloads corrupt.
        """
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/png"}
            mock_response.content = self.PNG_HEADER
            mock_response.text = "CORRUPTED TEXT VERSION"
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://example.com/image.png", "method": "GET"}
            action = node.run(shared)

            # Verify binary was detected and handled correctly
            assert action == "default"
            assert shared["response_is_binary"] is True
            assert isinstance(shared["response"], str)  # Base64 is a string
            # Verify can decode back to original
            decoded = base64.b64decode(shared["response"])
            assert decoded == self.PNG_HEADER

    def test_binary_uses_response_content_not_text(self):
        """Catch: Code accidentally uses response.text for binary → THE ORIGINAL BUG.

        This was the bug that started this whole task.
        If regression happens, this test fails immediately.
        """
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/png"}
            mock_response.content = self.PNG_HEADER
            # Make .text return garbage to prove we don't use it
            mock_response.text = "GARBAGE\x00\xff\xfe"
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://example.com/image.png", "method": "GET"}
            node.run(shared)

            # If we used .text, decoded data would be garbage
            decoded = base64.b64decode(shared["response"])
            assert decoded == self.PNG_HEADER
            assert decoded != b"GARBAGE\x00\xff\xfe"

    def test_all_binary_content_types_detected(self):
        """Catch: Some binary types missing from BINARY_CONTENT_TYPES list.

        Ensures complete coverage of common binary types.
        If new type added to code but this test not updated, we catch it.
        """
        binary_types = [
            "image/jpeg",
            "image/png",
            "video/mp4",
            "audio/mpeg",
            "application/pdf",
            "application/octet-stream",
            "application/zip",
            "application/gzip",
        ]

        for content_type in binary_types:
            with patch("requests.request") as mock_request:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.headers = {"content-type": content_type}
                mock_response.content = b"binary data"
                mock_response.elapsed = timedelta(seconds=0.1)
                mock_request.return_value = mock_response

                node = HttpNode()
                shared = {"url": "https://example.com/file", "method": "GET"}
                node.run(shared)

                assert shared["response_is_binary"] is True, f"{content_type} should be detected as binary"

    def test_text_content_not_falsely_detected_as_binary(self):
        """Catch: Text content-types trigger binary path → saves garbage.

        Prevents false positives that would break text downloads.
        """
        text_types = ["text/html", "text/plain", "text/css", "text/javascript"]

        for content_type in text_types:
            with patch("requests.request") as mock_request:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.headers = {"content-type": content_type}
                mock_response.text = "Hello, World!"
                mock_response.content = b"Hello, World!"
                mock_response.elapsed = timedelta(seconds=0.1)
                mock_request.return_value = mock_response

                node = HttpNode()
                shared = {"url": "https://example.com/file.txt", "method": "GET"}
                node.run(shared)

                assert shared["response_is_binary"] is False, f"{content_type} should NOT be detected as binary"
                assert shared["response"] == "Hello, World!"

    def test_json_still_works_not_detected_as_binary(self):
        """Catch: JSON detection broken by binary logic → critical backward compatibility.

        JSON responses are very common. If this breaks, many workflows fail.
        """
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = {"key": "value", "number": 42}
            mock_response.text = '{"key": "value", "number": 42}'
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/data", "method": "GET"}
            node.run(shared)

            # Verify JSON handling unchanged
            assert shared["response_is_binary"] is False
            assert isinstance(shared["response"], dict)
            assert shared["response"]["key"] == "value"
            assert shared["response"]["number"] == 42

    def test_content_type_with_parameters_still_detected(self):
        """Catch: Content-Type with parameters not detected → substring matching broken.

        Real servers often send: "image/png; charset=utf-8"
        Must use substring matching, not exact match.
        """
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "image/png; charset=utf-8"}
            mock_response.content = self.PNG_HEADER
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://example.com/image.png", "method": "GET"}
            node.run(shared)

            assert shared["response_is_binary"] is True
            decoded = base64.b64decode(shared["response"])
            assert decoded == self.PNG_HEADER

    def test_base64_encoding_preserves_data_integrity(self):
        """Catch: Base64 encoding corrupts data → write-file writes corrupted file.

        This is the final verification that binary data survives encoding.
        If this fails, downloaded files are corrupted even if everything else works.
        """
        # Use larger binary data with varied bytes to test encoding robustness
        test_data = bytes(range(256)) + b"\x00" * 100 + b"\xff" * 100

        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/octet-stream"}
            mock_response.content = test_data
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://example.com/data.bin", "method": "GET"}
            node.run(shared)

            # Verify round-trip: original → base64 → decoded = original
            assert shared["response_is_binary"] is True
            decoded = base64.b64decode(shared["response"])
            assert decoded == test_data
            assert len(decoded) == len(test_data)
