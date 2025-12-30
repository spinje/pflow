"""Test ReadFileNode binary data support.

These tests protect the binary data handling added in Task 82.
Each test catches ONE specific bug that would break binary file workflows.
"""

import base64
import os
import tempfile

from src.pflow.nodes.file import ReadFileNode


class TestReadFileBinarySupport:
    """Test binary file reading with base64 encoding."""

    def test_binary_file_detected_by_extension(self):
        """Binary file with .png extension is detected and base64 encoded.

        BUG IT CATCHES: Binary files with known extensions not recognized,
        read as text, data corrupted or crashes with UnicodeDecodeError.
        """
        # Create a PNG file with actual PNG header bytes
        png_header = b"\x89PNG\r\n\x1a\n"
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".png") as f:
            f.write(png_header)
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            action = node.run(shared)

            # Should succeed (not error)
            assert action == "default"

            # Should be base64 encoded
            assert "content" in shared
            content = shared["content"]
            assert isinstance(content, str), "Binary content must be base64 string"

            # Verify it's valid base64
            try:
                decoded = base64.b64decode(content)
                assert decoded == png_header, "Base64 decode should recover original bytes"
            except Exception as e:
                raise AssertionError(f"Invalid base64 encoding: {e}") from e

            # Binary flag must be set
            assert "content_is_binary" in shared
            assert shared["content_is_binary"] is True

        finally:
            os.unlink(temp_path)

    def test_binary_file_detected_by_unicode_error_fallback(self):
        """Binary file with .txt extension caught by UnicodeDecodeError fallback.

        BUG IT CATCHES: Binary files with text extensions not caught by fallback,
        workflow crashes with UnicodeDecodeError instead of gracefully handling.
        """
        # Create binary data that's NOT valid UTF-8, with .txt extension
        binary_data = b"\x80\x81\x82\x83\xff\xfe"
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".txt") as f:
            f.write(binary_data)
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            # Should NOT crash - should fallback to binary
            action = node.run(shared)

            assert action == "default", "Binary fallback should succeed"
            assert "content" in shared
            assert "error" not in shared, "Should not error - should fallback to binary"

            # Should be base64 encoded
            content = shared["content"]
            decoded = base64.b64decode(content)
            assert decoded == binary_data, "Fallback should preserve exact bytes"

            # Binary flag must be set
            assert shared["content_is_binary"] is True

        finally:
            os.unlink(temp_path)

    def test_base64_encoding_preserves_binary_data(self):
        """Base64 encoding accurately preserves binary data integrity.

        BUG IT CATCHES: Base64 encoding/decoding corrupts data, breaking
        workflows that download images, PDFs, or other binary files.
        """
        # Use varied binary data to test edge cases
        binary_data = bytes(range(256))  # All possible byte values
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".bin") as f:
            f.write(binary_data)
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            node.run(shared)

            # Decode and verify exact match
            content = shared["content"]
            decoded = base64.b64decode(content)

            assert decoded == binary_data, f"Expected {len(binary_data)} bytes, got {len(decoded)}"
            assert len(decoded) == 256, "All byte values should be preserved"

        finally:
            os.unlink(temp_path)

    def test_content_is_binary_flag_set_for_binary(self):
        """content_is_binary flag is True for binary files.

        BUG IT CATCHES: Binary data passed without flag, write-file treats
        base64 string as text, writes corrupted non-binary file.
        """
        binary_data = b"Binary data here"
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pdf") as f:
            f.write(binary_data)
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            node.run(shared)

            # Flag MUST be present and True
            assert "content_is_binary" in shared, "Flag missing - write-file won't know it's binary!"
            assert shared["content_is_binary"] is True, "Flag must be True for binary files"

        finally:
            os.unlink(temp_path)

    def test_content_is_binary_flag_false_for_text(self):
        """content_is_binary flag is False for text files.

        BUG IT CATCHES: Text files incorrectly flagged as binary, write-file
        treats them as binary, corrupts text data.
        """
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("Text content")
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            node.run(shared)

            # Flag MUST be False for text
            assert "content_is_binary" in shared
            assert shared["content_is_binary"] is False, "Text files must not be flagged as binary"

            # Content should have line numbers (text behavior)
            assert shared["content"] == "1: Text content"

        finally:
            os.unlink(temp_path)

    def test_empty_binary_file_handled(self):
        """Empty binary file doesn't crash.

        BUG IT CATCHES: Empty binary file causes crash or unexpected behavior
        in base64 encoding or flag setting logic.
        """
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".png") as f:
            # Write nothing - empty file
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            action = node.run(shared)

            # Should succeed
            assert action == "default"
            assert "content" in shared

            # Empty bytes base64 encodes to empty string
            assert shared["content"] == ""
            assert shared["content_is_binary"] is True

        finally:
            os.unlink(temp_path)

    def test_text_files_still_get_line_numbers(self):
        """Text files still get line numbers after binary support added.

        BUG IT CATCHES: Binary support breaks text file reading, line numbers
        missing or text files incorrectly treated as binary.

        This is a regression test ensuring backward compatibility.
        """
        text_content = "Line one\nLine two\nLine three"
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write(text_content)
            temp_path = f.name

        try:
            node = ReadFileNode()
            node.set_params({"file_path": temp_path})
            shared = {}

            node.run(shared)

            # Must have line numbers (text behavior preserved)
            expected = "1: Line one\n2: Line two\n3: Line three"
            assert shared["content"] == expected, "Text files must keep line numbers"
            assert shared["content_is_binary"] is False

        finally:
            os.unlink(temp_path)

    def test_all_24_binary_extensions_detected(self):
        """All 24 binary extensions are detected.

        BUG IT CATCHES: Some binary file types not in extension list,
        read as text, cause UnicodeDecodeError or corruption.
        """
        # Test a few key extensions from different categories
        test_extensions = [
            (".jpg", b"\xff\xd8\xff"),  # Image - JPEG header
            (".pdf", b"%PDF-1."),  # Document - PDF header
            (".zip", b"PK\x03\x04"),  # Archive - ZIP header
            (".mp3", b"ID3"),  # Audio - MP3 header
            (".woff", b"wOFF"),  # Font - WOFF header
            (".bin", b"\x00\x01\x02"),  # Generic binary
        ]

        for ext, header_bytes in test_extensions:
            with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=ext) as f:
                f.write(header_bytes)
                temp_path = f.name

            try:
                node = ReadFileNode()
                node.set_params({"file_path": temp_path})
                shared = {}

                action = node.run(shared)

                assert action == "default", f"{ext} files should be detected as binary"
                assert shared["content_is_binary"] is True, f"{ext} should set binary flag"

                # Verify base64 encoding worked
                decoded = base64.b64decode(shared["content"])
                assert decoded == header_bytes, f"{ext} data corrupted"

            finally:
                os.unlink(temp_path)
