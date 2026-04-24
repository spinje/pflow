"""Tests for LLM node image support."""

import pytest

from pflow.core.llm_client import Attachment
from pflow.nodes.llm.llm import LLMNode


@pytest.fixture
def temp_image(tmp_path):
    """Create a temporary image file for testing."""
    image_file = tmp_path / "test.jpg"
    image_file.write_bytes(b"fake image data")
    return str(image_file)


def test_single_url_image(mock_llm_client):
    """LLMNode forwards a single URL image as an Attachment(image_url)."""
    node = LLMNode()
    node.set_params({"prompt": "Describe this image", "images": ["https://example.com/image.jpg"]})
    shared = {}

    action = node.run(shared)

    assert action == "default"
    attachments = mock_llm_client.call_history[-1]["attachments"]
    assert len(attachments) == 1
    assert isinstance(attachments[0], Attachment)
    assert attachments[0].kind == "image_url"
    assert attachments[0].value == "https://example.com/image.jpg"


def test_single_file_image(temp_image, mock_llm_client):
    """LLMNode forwards a single file path as an Attachment(image_path)."""
    node = LLMNode()
    node.set_params({"prompt": "What's this?", "images": [temp_image]})
    shared = {}

    action = node.run(shared)

    assert action == "default"
    attachments = mock_llm_client.call_history[-1]["attachments"]
    assert len(attachments) == 1
    assert attachments[0].kind == "image_path"
    assert attachments[0].value == temp_image


def test_multiple_images_mixed(temp_image, mock_llm_client):
    """LLMNode preserves order across mixed URL/file images."""
    node = LLMNode()
    node.set_params({
        "prompt": "Compare these",
        "images": ["https://example.com/img1.jpg", temp_image, "https://example.com/img2.png"],
    })
    shared = {}

    action = node.run(shared)

    assert action == "default"
    attachments = mock_llm_client.call_history[-1]["attachments"]
    assert len(attachments) == 3
    assert attachments[0].kind == "image_url"
    assert attachments[0].value == "https://example.com/img1.jpg"
    assert attachments[1].kind == "image_path"
    assert attachments[1].value == temp_image
    assert attachments[2].kind == "image_url"
    assert attachments[2].value == "https://example.com/img2.png"


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


def test_empty_images_backward_compatibility(mock_llm_client):
    """Empty images list passes None to the adapter (no attachments arg)."""
    node = LLMNode()
    node.set_params({"prompt": "Hello world", "images": []})
    shared = {}

    action = node.run(shared)

    assert action == "default"
    # LLMNode passes attachments=None to the adapter when the list is empty
    assert mock_llm_client.call_history[-1]["attachments"] is None


def test_no_images_backward_compatibility(mock_llm_client):
    """Missing images key passes None to the adapter."""
    node = LLMNode()
    node.set_params({"prompt": "Hello world"})  # No images key at all
    shared = {}

    action = node.run(shared)

    assert action == "default"
    assert mock_llm_client.call_history[-1]["attachments"] is None


def test_images_from_params(temp_image, mock_llm_client):
    """Direct params assignment works the same as set_params."""
    node = LLMNode()
    node.params = {"prompt": "Test", "images": [temp_image]}
    shared = {}

    action = node.run(shared)

    assert action == "default"
    attachments = mock_llm_client.call_history[-1]["attachments"]
    assert len(attachments) == 1
    assert attachments[0].kind == "image_path"
    assert attachments[0].value == temp_image


def test_single_string_auto_wrapping(temp_image, mock_llm_client):
    """A single string in `images` gets wrapped into a list of one."""
    node = LLMNode()
    node.set_params({"prompt": "Describe", "images": temp_image})  # String, not list
    shared = {}

    action = node.run(shared)

    assert action == "default"
    attachments = mock_llm_client.call_history[-1]["attachments"]
    assert len(attachments) == 1
    assert attachments[0].kind == "image_path"
    assert attachments[0].value == temp_image


def test_http_url_detection(mock_llm_client):
    """http:// (not just https://) URLs are detected as URL attachments."""
    node = LLMNode()
    node.set_params({"prompt": "Describe", "images": ["http://example.com/image.jpg"]})
    shared = {}

    action = node.run(shared)

    assert action == "default"
    attachments = mock_llm_client.call_history[-1]["attachments"]
    assert attachments[0].kind == "image_url"
    assert attachments[0].value == "http://example.com/image.jpg"


def test_images_with_system_and_max_tokens(temp_image, mock_llm_client):
    """Images work alongside system + max_tokens params."""
    node = LLMNode()
    node.set_params({
        "prompt": "Analyze",
        "system": "You are an expert",
        "images": [temp_image],
        "max_tokens": 100,
    })
    shared = {}

    action = node.run(shared)

    assert action == "default"
    last = mock_llm_client.call_history[-1]
    assert last["system"] == "You are an expert"
    assert last["max_tokens"] == 100
    assert len(last["attachments"]) == 1


def test_relative_file_path(tmp_path, mock_llm_client):
    """Relative paths resolve against the current working directory."""
    image_file = tmp_path / "relative.jpg"
    image_file.write_bytes(b"test")

    import os

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)

        node = LLMNode()
        node.set_params({"prompt": "Test", "images": ["relative.jpg"]})
        shared = {}

        action = node.run(shared)

        assert action == "default"
        attachments = mock_llm_client.call_history[-1]["attachments"]
        assert len(attachments) == 1
        assert attachments[0].kind == "image_path"
    finally:
        os.chdir(original_cwd)
