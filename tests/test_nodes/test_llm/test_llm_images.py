"""Tests for LLM node image support."""

from unittest.mock import Mock, patch

import llm
import pytest

from pflow.nodes.llm.llm import LLMNode


@pytest.fixture
def temp_image(tmp_path):
    """Create a temporary image file for testing."""
    image_file = tmp_path / "test.jpg"
    image_file.write_bytes(b"fake image data")
    return str(image_file)


@pytest.fixture
def mock_llm_response():
    """Create a mock LLM response."""
    mock_response = Mock()
    mock_response.text.return_value = "Test response"
    mock_response.usage.return_value = None
    return mock_response


def test_single_url_image(mock_llm_response):
    """Test LLM node with single URL image."""
    node = LLMNode()
    node.set_params({"prompt": "Describe this image", "images": ["https://example.com/image.jpg"]})
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model
        mock_llm.Attachment = llm.Attachment  # Use real Attachment class

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Test response"

        # Verify attachments were passed correctly
        call_kwargs = mock_model.prompt.call_args[1]
        assert "attachments" in call_kwargs
        assert len(call_kwargs["attachments"]) == 1
        assert call_kwargs["attachments"][0].url == "https://example.com/image.jpg"


def test_single_file_image(temp_image, mock_llm_response):
    """Test LLM node with single file path."""
    node = LLMNode()
    node.set_params({"prompt": "What's this?", "images": [temp_image]})
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model
        mock_llm.Attachment = llm.Attachment

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Test response"

        # Verify file attachment
        call_kwargs = mock_model.prompt.call_args[1]
        assert len(call_kwargs["attachments"]) == 1
        assert call_kwargs["attachments"][0].path == temp_image


def test_multiple_images_mixed(temp_image, mock_llm_response):
    """Test LLM node with multiple images (URL + file)."""
    node = LLMNode()
    node.set_params({
        "prompt": "Compare these",
        "images": ["https://example.com/img1.jpg", temp_image, "https://example.com/img2.png"],
    })
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model
        mock_llm.Attachment = llm.Attachment

        action = node.run(shared)

        assert action == "default"

        # Verify all attachments
        call_kwargs = mock_model.prompt.call_args[1]
        assert len(call_kwargs["attachments"]) == 3
        assert call_kwargs["attachments"][0].url == "https://example.com/img1.jpg"
        assert call_kwargs["attachments"][1].path == temp_image
        assert call_kwargs["attachments"][2].url == "https://example.com/img2.png"


def test_missing_file_error():
    """Test that missing file raises ValueError."""
    node = LLMNode()
    node.set_params({"prompt": "Describe", "images": ["/nonexistent/file.jpg"]})
    shared = {}

    with pytest.raises(ValueError) as exc_info:
        node.run(shared)

    assert "not found" in str(exc_info.value).lower()


def test_invalid_image_type():
    """Test that non-string image raises TypeError."""
    node = LLMNode()
    node.set_params({"prompt": "Describe", "images": [123]})  # Integer instead of string
    shared = {}

    with pytest.raises(TypeError) as exc_info:
        node.run(shared)

    assert "must be a string" in str(exc_info.value).lower()


def test_empty_images_backward_compatibility(mock_llm_response):
    """Test that empty images list doesn't break existing functionality."""
    node = LLMNode()
    node.set_params({"prompt": "Hello world", "images": []})
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Test response"

        # Verify attachments NOT passed when empty
        call_kwargs = mock_model.prompt.call_args[1]
        assert "attachments" not in call_kwargs


def test_no_images_backward_compatibility(mock_llm_response):
    """Test that missing images key works (backward compatibility)."""
    node = LLMNode()
    node.set_params({"prompt": "Hello world"})  # No images key at all
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model

        action = node.run(shared)

        assert action == "default"
        assert shared["response"] == "Test response"

        # Verify attachments NOT passed
        call_kwargs = mock_model.prompt.call_args[1]
        assert "attachments" not in call_kwargs


def test_images_from_params(temp_image, mock_llm_response):
    """Test images from params."""
    node = LLMNode()
    node.params = {"prompt": "Test", "images": [temp_image]}
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model
        mock_llm.Attachment = llm.Attachment

        action = node.run(shared)

        assert action == "default"

        # Verify image from params was used
        call_kwargs = mock_model.prompt.call_args[1]
        assert len(call_kwargs["attachments"]) == 1
        assert call_kwargs["attachments"][0].path == temp_image


def test_single_string_auto_wrapping(temp_image, mock_llm_response):
    """Test that single string is automatically wrapped in list."""
    node = LLMNode()
    node.set_params({"prompt": "Describe", "images": temp_image})  # String, not list
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model
        mock_llm.Attachment = llm.Attachment

        action = node.run(shared)

        assert action == "default"

        # Verify single string was wrapped and processed
        call_kwargs = mock_model.prompt.call_args[1]
        assert len(call_kwargs["attachments"]) == 1
        assert call_kwargs["attachments"][0].path == temp_image


def test_http_url_detection(mock_llm_response):
    """Test that http:// URLs are detected correctly."""
    node = LLMNode()
    node.set_params({"prompt": "Describe", "images": ["http://example.com/image.jpg"]})
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model
        mock_llm.Attachment = llm.Attachment

        action = node.run(shared)

        assert action == "default"

        # Verify http URL detected as URL
        call_kwargs = mock_model.prompt.call_args[1]
        assert call_kwargs["attachments"][0].url == "http://example.com/image.jpg"


def test_images_with_system_and_max_tokens(temp_image, mock_llm_response):
    """Test images work correctly with other optional parameters."""
    node = LLMNode()
    node.set_params({
        "prompt": "Analyze",
        "system": "You are an expert",
        "images": [temp_image],
        "max_tokens": 100,
    })
    shared = {}

    with patch("pflow.nodes.llm.llm.llm") as mock_llm:
        mock_model = Mock()
        mock_model.prompt.return_value = mock_llm_response
        mock_llm.get_model.return_value = mock_model
        mock_llm.Attachment = llm.Attachment

        action = node.run(shared)

        assert action == "default"

        # Verify all parameters were passed
        call_kwargs = mock_model.prompt.call_args[1]
        assert call_kwargs["system"] == "You are an expert"
        assert call_kwargs["max_tokens"] == 100
        assert len(call_kwargs["attachments"]) == 1


def test_relative_file_path(tmp_path, mock_llm_response):
    """Test that relative file paths work."""
    # Create image in temp directory
    image_file = tmp_path / "relative.jpg"
    image_file.write_bytes(b"test")

    # Change to temp directory for relative path to work
    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        node = LLMNode()
        node.set_params({"prompt": "Test", "images": ["relative.jpg"]})
        shared = {}

        with patch("pflow.nodes.llm.llm.llm") as mock_llm:
            mock_model = Mock()
            mock_model.prompt.return_value = mock_llm_response
            mock_llm.get_model.return_value = mock_model
            mock_llm.Attachment = llm.Attachment

            action = node.run(shared)

            assert action == "default"

            # Verify relative path was processed
            call_kwargs = mock_model.prompt.call_args[1]
            assert len(call_kwargs["attachments"]) == 1
    finally:
        os.chdir(original_cwd)
