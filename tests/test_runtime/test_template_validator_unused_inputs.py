"""Test suite for unused input detection in TemplateValidator.

This module tests the Task 17 Subtask 5 enhancement that detects when
declared inputs are never used as template variables in the workflow.
"""

import pytest

from pflow.registry import Registry
from pflow.runtime.template_validator import TemplateValidator


class MockRegistry(Registry):
    """Mock registry for testing with predefined node metadata."""

    def __init__(self, nodes_metadata: dict):
        super().__init__()
        self._nodes_metadata = nodes_metadata

    def get_nodes_metadata(self, node_types: list[str]) -> dict:
        """Return mock metadata for requested node types."""
        result = {}
        for node_type in node_types:
            if node_type in self._nodes_metadata:
                result[node_type] = self._nodes_metadata[node_type]
        return result


@pytest.fixture
def mock_registry():
    """Create a mock registry with basic node metadata."""
    nodes_metadata = {
        "read-file": {
            "interface": {
                "inputs": [],
                "outputs": [{"key": "content", "type": "string"}],
                "parameters": [{"key": "path", "type": "string", "required": True}],
            }
        },
        "write-file": {
            "interface": {
                "inputs": [{"key": "content", "type": "string"}],
                "outputs": [],
                "parameters": [{"key": "path", "type": "string", "required": True}],
            }
        },
        "transform": {
            "interface": {
                "inputs": [{"key": "data", "type": "any"}],
                "outputs": [{"key": "result", "type": "any", "structure": {"status": "string", "value": "any"}}],
                "parameters": [],
            }
        },
        "http": {
            "interface": {
                "inputs": [],
                "outputs": [
                    {"key": "response", "type": "any"},
                    {"key": "status_code", "type": "integer"},
                    {"key": "headers", "type": "dict"},
                ],
                "parameters": [
                    {"key": "url", "type": "string", "required": True},
                    {"key": "method", "type": "string", "required": False},
                    {"key": "headers", "type": "dict", "required": False},
                    {"key": "body", "type": "any", "required": False},
                    {"key": "params", "type": "dict", "required": False},
                    {"key": "auth_token", "type": "string", "required": False},
                    {"key": "api_key", "type": "string", "required": False},
                ],
            }
        },
        "llm": {
            "interface": {
                "inputs": [],
                "outputs": [{"key": "response", "type": "any"}],
                "parameters": [
                    {"key": "prompt", "type": "string", "required": True},
                    {"key": "system", "type": "string", "required": False},
                    {"key": "model", "type": "string", "required": False},
                ],
            }
        },
    }
    return MockRegistry(nodes_metadata)


def test_unused_input_single_unused(mock_registry, tmp_path):
    """Test detection of a single unused input."""
    output_path = str(tmp_path / "output.txt")
    input_path = str(tmp_path / "input.txt")
    workflow_ir = {
        "inputs": {
            "input_path": {"type": "string", "description": "Path to input file"},
            "unused_param": {"type": "string", "description": "This parameter is never used"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${input_path}"},  # Uses input_path
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": output_path},  # Doesn't use unused_param
            },
        ],
    }

    initial_params = {"input_path": input_path}  # unused_param not provided

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have exactly one error about unused input
    assert len(errors) == 1
    assert "Declared input(s) never used as template variable: unused_param" in errors[0]


def test_all_inputs_used(mock_registry, tmp_path):
    """Test when all declared inputs are properly used."""
    input_path = str(tmp_path / "input.txt")
    output_path = str(tmp_path / "output.txt")
    workflow_ir = {
        "inputs": {
            "input_path": {"type": "string", "description": "Path to input file"},
            "output_path": {"type": "string", "description": "Path to output file"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${input_path}"},  # Uses input_path
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${output_path}"},  # Uses output_path
            },
        ],
    }

    initial_params = {"input_path": input_path, "output_path": output_path}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors
    assert len(errors) == 0


def test_empty_inputs_field(mock_registry, tmp_path):
    """Test when inputs field is empty or missing."""
    # Test with empty inputs dict
    hardcoded = str(tmp_path / "hardcoded.txt")
    workflow_ir = {
        "inputs": {},
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": hardcoded},
            }
        ],
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, {}, mock_registry)
    assert len(errors) == 0

    # Test with missing inputs field
    workflow_ir_no_inputs = {
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": hardcoded},
            }
        ]
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir_no_inputs, {}, mock_registry)
    assert len(errors) == 0


def test_input_used_in_nested_path(mock_registry, tmp_path):
    """Test when input is used with nested path access (e.g., ${input.field})."""
    input_path = str(tmp_path / "input.txt")
    output_path = str(tmp_path / "output.txt")
    workflow_ir = {
        "inputs": {
            "config": {"type": "object", "description": "Configuration object"},
            "api_settings": {"type": "object", "description": "API settings"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${config.input_file}"},  # Uses config with nested path
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${api_settings.endpoint.url}"},  # Uses api_settings with nested path
            },
        ],
    }

    initial_params = {
        "config": {"input_file": input_path},
        "api_settings": {"endpoint": {"url": output_path}},
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - both inputs are used even though with nested paths
    assert len(errors) == 0


def test_multiple_unused_inputs(mock_registry, tmp_path):
    """Test that multiple unused inputs are all reported."""
    workflow_ir = {
        "inputs": {
            "used_param": {"type": "string", "description": "This is used"},
            "unused1": {"type": "string", "description": "First unused"},
            "unused2": {"type": "integer", "description": "Second unused"},
            "unused3": {"type": "boolean", "description": "Third unused"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${used_param}"},  # Only uses used_param
            }
        ],
    }

    initial_params = {"used_param": str(tmp_path / "file.txt")}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have exactly one error listing all unused inputs
    assert len(errors) == 1
    error_msg = errors[0]
    assert "Declared input(s) never used as template variable:" in error_msg
    # Check all unused inputs are mentioned (in sorted order)
    assert "unused1" in error_msg
    assert "unused2" in error_msg
    assert "unused3" in error_msg
    # Verify they're in sorted order
    assert error_msg.endswith("unused1, unused2, unused3")


def test_node_output_not_flagged_as_unused_input(mock_registry, tmp_path):
    """Test that node outputs aren't mistakenly flagged as unused inputs."""
    output_path = str(tmp_path / "output.txt")
    input_path = str(tmp_path / "input.txt")
    workflow_ir = {
        "inputs": {
            "input_file": {"type": "string", "description": "Input file path"},
        },
        "outputs": {
            "content": {"type": "string", "description": "File content"},  # This is an output, not input
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${input_file}"},  # Uses the input
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": output_path},
            },
        ],
    }

    initial_params = {"input_file": input_path}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - outputs aren't inputs
    assert len(errors) == 0


def test_input_used_multiple_times(mock_registry, tmp_path):
    """Test when an input is used multiple times in different nodes."""
    workflow_ir = {
        "inputs": {
            "base_path": {"type": "string", "description": "Base path for files"},
        },
        "nodes": [
            {
                "id": "reader1",
                "type": "read-file",
                "params": {"path": "${base_path}/file1.txt"},  # First use
            },
            {
                "id": "reader2",
                "type": "read-file",
                "params": {"path": "${base_path}/file2.txt"},  # Second use
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${base_path}/output.txt"},  # Third use
            },
        ],
    }

    initial_params = {"base_path": str(tmp_path)}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - input is used
    assert len(errors) == 0


def test_mixed_used_and_unused_inputs(mock_registry, tmp_path):
    """Test workflow with both used and unused inputs."""
    workflow_ir = {
        "inputs": {
            "used1": {"type": "string", "description": "First used input"},
            "unused1": {"type": "string", "description": "First unused input"},
            "used2": {"type": "string", "description": "Second used input"},
            "unused2": {"type": "string", "description": "Second unused input"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${used1}"},
            },
            {
                "id": "writer",
                "type": "write-file",
                "params": {"path": "${used2}"},
            },
        ],
    }

    initial_params = {"used1": str(tmp_path / "input.txt"), "used2": str(tmp_path / "output.txt")}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have one error about unused inputs
    assert len(errors) == 1
    error_msg = errors[0]
    assert "Declared input(s) never used as template variable:" in error_msg
    assert "unused1, unused2" in error_msg


def test_input_only_used_in_concatenation(mock_registry, tmp_path):
    """Test when input is used within string concatenation."""
    base = str(tmp_path)
    workflow_ir = {
        "inputs": {
            "prefix": {"type": "string", "description": "Filename prefix"},
            "suffix": {"type": "string", "description": "Filename suffix"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": base + "/${prefix}-file-${suffix}.txt"},  # Both used in concatenation
            }
        ],
    }

    initial_params = {"prefix": "test", "suffix": "data"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - both inputs are used
    assert len(errors) == 0


def test_unused_input_with_missing_required_input(mock_registry):
    """Test when there are both unused inputs and missing required inputs."""
    workflow_ir = {
        "inputs": {
            "required_path": {"type": "string", "description": "Required path", "required": True},
            "unused_param": {"type": "string", "description": "Unused parameter"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${required_path}"},  # Uses required_path
            }
        ],
    }

    # Don't provide the required input
    initial_params = {}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have two errors: one for missing required, one for unused
    assert len(errors) == 2

    error_messages = " ".join(errors)
    assert "unused_param" in error_messages
    assert "required_path" in error_messages


def test_case_sensitivity_in_unused_detection(mock_registry, tmp_path):
    """Test that unused input detection is case-sensitive."""
    workflow_ir = {
        "inputs": {
            "MyInput": {"type": "string", "description": "Camel case input"},
            "myinput": {"type": "string", "description": "Lower case input"},
        },
        "nodes": [
            {
                "id": "reader",
                "type": "read-file",
                "params": {"path": "${MyInput}"},  # Uses MyInput (camel case)
            }
        ],
    }

    initial_params = {"MyInput": str(tmp_path / "file.txt")}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have one error about unused 'myinput' (lowercase)
    assert len(errors) == 1
    assert "myinput" in errors[0]
    assert "MyInput" not in errors[0]  # MyInput is used


# ===== Tests for Nested Template Variables (Bug Fix) =====
# These tests verify that template variables in nested structures (dicts, lists)
# are properly detected and not incorrectly flagged as unused


def test_nested_headers_with_templates(mock_registry):
    """Test template variables in nested headers dictionary (HTTP node scenario)."""
    workflow_ir = {
        "inputs": {
            "api_token": {"type": "string", "description": "API authentication token"},
            "channel_id": {"type": "string", "description": "Slack channel ID"},
            "api_key": {"type": "string", "description": "API key for authentication"},
        },
        "nodes": [
            {
                "id": "api_call",
                "type": "http",
                "params": {
                    "url": "https://api.example.com/endpoint",
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer ${api_token}",  # Nested in headers dict
                        "X-Channel-ID": "${channel_id}",  # Also nested
                        "X-API-Key": "${api_key}",  # Also nested
                    },
                },
            }
        ],
    }

    initial_params = {"api_token": "token123", "channel_id": "C123", "api_key": "key456"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - all inputs are used in nested headers
    assert len(errors) == 0


def test_nested_body_with_templates(mock_registry):
    """Test template variables in nested body dictionary."""
    workflow_ir = {
        "inputs": {
            "message": {"type": "string", "description": "Message content"},
            "user_id": {"type": "string", "description": "User identifier"},
            "timestamp": {"type": "string", "description": "Message timestamp"},
        },
        "nodes": [
            {
                "id": "send_message",
                "type": "http",
                "params": {
                    "url": "https://api.example.com/messages",
                    "method": "POST",
                    "body": {
                        "text": "${message}",  # Nested in body dict
                        "user": "${user_id}",  # Also nested
                        "sent_at": "${timestamp}",  # Also nested
                    },
                },
            }
        ],
    }

    initial_params = {"message": "Hello", "user_id": "user123", "timestamp": "2024-01-01T00:00:00Z"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - all inputs are used in nested body
    assert len(errors) == 0


def test_nested_params_with_templates(mock_registry):
    """Test template variables in nested params dictionary (query parameters)."""
    workflow_ir = {
        "inputs": {
            "search_query": {"type": "string", "description": "Search term"},
            "page_size": {"type": "string", "description": "Results per page"},
            "sort_order": {"type": "string", "description": "Sort order"},
        },
        "nodes": [
            {
                "id": "search",
                "type": "http",
                "params": {
                    "url": "https://api.example.com/search",
                    "method": "GET",
                    "params": {
                        "q": "${search_query}",  # Nested in params dict
                        "limit": "${page_size}",  # Also nested
                        "sort": "${sort_order}",  # Also nested
                    },
                },
            }
        ],
    }

    initial_params = {"search_query": "test", "page_size": "10", "sort_order": "desc"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - all inputs are used in nested params
    assert len(errors) == 0


def test_deeply_nested_templates(mock_registry):
    """Test template variables in deeply nested structures."""
    workflow_ir = {
        "inputs": {
            "api_key": {"type": "string", "description": "API key"},
            "user_name": {"type": "string", "description": "User name"},
            "project_id": {"type": "string", "description": "Project ID"},
            "task_id": {"type": "string", "description": "Task ID"},
        },
        "nodes": [
            {
                "id": "complex_api",
                "type": "http",
                "params": {
                    "url": "https://api.example.com/complex",
                    "body": {
                        "auth": {
                            "credentials": {
                                "api_key": "${api_key}",  # 3 levels deep
                            }
                        },
                        "data": {
                            "user": {
                                "name": "${user_name}",  # 3 levels deep
                                "projects": {
                                    "current": "${project_id}",  # 4 levels deep
                                    "tasks": {
                                        "active": "${task_id}",  # 5 levels deep!
                                    },
                                },
                            }
                        },
                    },
                },
            }
        ],
    }

    initial_params = {"api_key": "key", "user_name": "Bob", "project_id": "P1", "task_id": "T1"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - all inputs are used even in deeply nested structures
    assert len(errors) == 0


def test_templates_in_lists(mock_registry):
    """Test template variables inside lists/arrays."""
    workflow_ir = {
        "inputs": {
            "item1": {"type": "string", "description": "First item"},
            "item2": {"type": "string", "description": "Second item"},
            "item3": {"type": "string", "description": "Third item"},
        },
        "nodes": [
            {
                "id": "list_processor",
                "type": "http",
                "params": {
                    "url": "https://api.example.com/process",
                    "body": {
                        "items": ["${item1}", "${item2}", "${item3}"],  # Templates in a list
                        "nested_lists": [
                            ["${item1}", "static"],
                            ["${item2}", "value"],
                            [{"key": "${item3}"}],  # Template in dict in list
                        ],
                    },
                },
            }
        ],
    }

    initial_params = {"item1": "a", "item2": "b", "item3": "c"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - all inputs are used in lists
    assert len(errors) == 0


def test_mixed_nested_and_toplevel_templates(mock_registry):
    """Test mix of top-level and nested template variables."""
    workflow_ir = {
        "inputs": {
            "direct_url": {"type": "string", "description": "Direct URL parameter"},
            "header_token": {"type": "string", "description": "Token for header"},
            "body_message": {"type": "string", "description": "Message for body"},
            "unused_param": {"type": "string", "description": "This one is not used"},
        },
        "nodes": [
            {
                "id": "mixed",
                "type": "http",
                "params": {
                    "url": "${direct_url}",  # Top-level template
                    "headers": {
                        "Authorization": "Bearer ${header_token}",  # Nested template
                    },
                    "body": {
                        "message": "${body_message}",  # Nested template
                    },
                },
            }
        ],
    }

    initial_params = {"direct_url": "https://api.com", "header_token": "token", "body_message": "hello"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have one error - unused_param is not used
    assert len(errors) == 1
    assert "unused_param" in errors[0]
    # But the other nested ones should not be reported as unused
    assert "direct_url" not in errors[0]
    assert "header_token" not in errors[0]
    assert "body_message" not in errors[0]


def test_nested_templates_with_multiple_nodes(mock_registry):
    """Test nested templates used across multiple nodes."""
    workflow_ir = {
        "inputs": {
            "auth_token": {"type": "string", "description": "Authentication token"},
            "api_key": {"type": "string", "description": "API key"},
            "channel": {"type": "string", "description": "Channel ID"},
        },
        "nodes": [
            {
                "id": "first_call",
                "type": "http",
                "params": {
                    "url": "https://api1.com",
                    "headers": {
                        "Authorization": "Bearer ${auth_token}",  # Used in first node
                    },
                },
            },
            {
                "id": "second_call",
                "type": "http",
                "params": {
                    "url": "https://api2.com",
                    "headers": {
                        "X-API-Key": "${api_key}",  # Used in second node
                    },
                    "body": {
                        "channel_id": "${channel}",  # Also used in second node
                    },
                },
            },
        ],
    }

    initial_params = {"auth_token": "token123", "api_key": "key456", "channel": "C789"}

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - all inputs are used across different nodes
    assert len(errors) == 0


def test_slack_google_sheets_real_scenario(mock_registry):
    """Test the real-world Slack + Google Sheets scenario that was failing."""
    workflow_ir = {
        "inputs": {
            "slack_channel_id": {
                "type": "string",
                "description": "Slack channel ID where messages will be fetched",
                "required": True,
            },
            "message_count": {
                "type": "number",
                "description": "Number of recent messages to fetch",
                "required": False,
                "default": 10,
            },
            "slack_bot_token": {
                "type": "string",
                "description": "Slack bot token for authentication",
                "required": True,
            },
            "google_sheets_api_key": {
                "type": "string",
                "description": "Google Sheets API key",
                "required": True,
            },
            "google_sheets_id": {"type": "string", "description": "Google Sheets ID", "required": True},
            "sheet_name": {"type": "string", "description": "Sheet name", "required": False, "default": "Sheet1"},
        },
        "nodes": [
            {
                "id": "fetch_messages",
                "type": "http",
                "params": {
                    "url": "https://slack.com/api/conversations.history",
                    "method": "GET",
                    "params": {
                        "channel": "${slack_channel_id}",  # Nested in params
                        "limit": "${message_count}",  # Also nested
                    },
                    "headers": {
                        "Authorization": "Bearer ${slack_bot_token}",  # Nested in headers
                    },
                },
            },
            {
                "id": "analyze",
                "type": "llm",
                "params": {
                    "prompt": "Analyze these messages from channel ${slack_channel_id}",  # Top-level string
                },
            },
            {
                "id": "send_responses",
                "type": "http",
                "params": {
                    "url": "https://slack.com/api/chat.postMessage",
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer ${slack_bot_token}",  # Reused in headers
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "channel": "${slack_channel_id}",  # Nested in body
                        "text": "Response text",
                    },
                },
            },
            {
                "id": "update_sheets",
                "type": "http",
                "params": {
                    "url": "https://sheets.googleapis.com/v4/spreadsheets/${google_sheets_id}/values/${sheet_name}:append",
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer ${google_sheets_api_key}",  # Nested in headers
                    },
                    "body": {"values": [["Q", "A"]]},
                },
            },
        ],
    }

    initial_params = {
        "slack_channel_id": "C123",
        "message_count": 10,
        "slack_bot_token": "xoxb-123",
        "google_sheets_api_key": "AIza123",
        "google_sheets_id": "1abc",
        "sheet_name": "Sheet1",
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have no errors - all inputs are properly used in various nested structures
    assert len(errors) == 0


def test_partially_used_nested_inputs(mock_registry):
    """Test when some inputs are used in nested structures and others are not."""
    workflow_ir = {
        "inputs": {
            "used_in_header": {"type": "string", "description": "Used in header"},
            "used_in_body": {"type": "string", "description": "Used in body"},
            "used_in_list": {"type": "string", "description": "Used in list"},
            "never_used": {"type": "string", "description": "Never used anywhere"},
            "also_never_used": {"type": "string", "description": "Also never used"},
        },
        "nodes": [
            {
                "id": "api",
                "type": "http",
                "params": {
                    "url": "https://api.example.com",
                    "headers": {
                        "X-Custom": "${used_in_header}",
                    },
                    "body": {
                        "data": {
                            "value": "${used_in_body}",
                            "items": ["item1", "${used_in_list}", "item3"],
                        }
                    },
                },
            }
        ],
    }

    initial_params = {
        "used_in_header": "h",
        "used_in_body": "b",
        "used_in_list": "l",
        "never_used": "n",
        "also_never_used": "a",
    }

    errors = TemplateValidator.validate_workflow_templates(workflow_ir, initial_params, mock_registry)

    # Should have one error listing both unused inputs
    assert len(errors) == 1
    assert "also_never_used" in errors[0]
    assert "never_used" in errors[0]
    # Used inputs should not be in the error
    assert "used_in_header" not in errors[0]
    assert "used_in_body" not in errors[0]
    assert "used_in_list" not in errors[0]
